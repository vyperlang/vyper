import pytest

from vyper.compiler.settings import OptimizationLevel
from vyper.ir.compile_ir import Label
from vyper.venom import generate_assembly_experimental
from vyper.venom.analysis import CFGAnalysis, IRAnalysesCache, LivenessAnalysis, MustHaltAnalysis
from vyper.venom.basicblock import IRLabel, IRVariable
from vyper.venom.context import IRContext
from vyper.venom.parser import parse_venom
from vyper.venom.stack_model import StackModel
from vyper.venom.stack_safety import StackCleanupSafety, _EVM_STACK_LIMIT
from vyper.venom.venom_to_assembly import VenomCompiler


def _get_stack_cleanup_analyses(ctx, fn_name="test"):
    analyses_caches = {candidate: IRAnalysesCache(candidate) for candidate in ctx.get_functions()}
    fn = ctx.get_function(IRLabel(fn_name))
    ac = analyses_caches[fn]
    liveness = ac.request_analysis(LivenessAnalysis)
    must_halt = ac.request_analysis(MustHaltAnalysis)
    safety = StackCleanupSafety(ctx, analyses_caches)
    return fn, liveness, must_halt, safety


def _block_opcodes(asm, label):
    start = next(
        i for i, item in enumerate(asm) if isinstance(item, Label) and str(item) == f"LABEL {label}"
    )
    end = next((i for i in range(start + 1, len(asm)) if isinstance(asm[i], Label)), len(asm))
    return [item for item in asm[start:end] if isinstance(item, str)]


def test_cleanup_stack():
    ctx = IRContext()
    fn = ctx.create_function("test")
    bb = fn.get_basic_block()
    ret_val = bb.append_instruction("param")
    op = bb.append_instruction("assign", 10)
    op2 = bb.append_instruction("assign", op)
    bb.append_instruction("add", op, op2)
    bb.append_instruction("ret", ret_val)

    asm = generate_assembly_experimental(ctx, optimize=OptimizationLevel.GAS)
    assert asm == ["PUSH1", 10, "DUP1", "ADD", "POP", "JUMP"]


@pytest.mark.parametrize(
    "terminator", ["return 0, 32", "revert 0, 32", "stop", "invalid", "selfdestruct 0"]
)
def test_cleanup_elided_for_direct_and_transitive_message_halts(terminator):
    ctx = parse_venom(f"""
        function test {{
        entry:
            %direct_value = calldataload 0
            %chain_value = calldataload 32
            %outer_cond = calldataload 64
            %chain_cond = calldataload 96
            jnz %outer_cond, @direct, @chain
        direct:
            mstore 0, %direct_value
            {terminator}
        chain:
            mstore 32, %chain_value
            jnz %chain_cond, @terminal_a, @terminal_b
        terminal_a:
            {terminator}
        terminal_b:
            {terminator}
        }}
    """)

    fn, _, must_halt, _ = _get_stack_cleanup_analyses(ctx)
    expected = {"entry", "direct", "chain", "terminal_a", "terminal_b"}
    assert expected == {bb.label.value for bb in must_halt.must_halt}

    asm = VenomCompiler(ctx).generate_evm_assembly(no_optimize=True)
    assert "POP" not in _block_opcodes(asm, "direct")
    assert "POP" not in _block_opcodes(asm, "chain")
    assert fn.get_basic_block("direct").is_halting
    assert not fn.get_basic_block("chain").is_halting


def test_only_guaranteed_halting_branch_region_retains_junk():
    def compile_candidate(right_terminator):
        ctx = parse_venom(f"""
            function test {{
            entry:
                %retpc = param
                %junk = calldataload 0
                %outer = calldataload 32
                jnz %outer, @candidate, @outer_halt
            candidate:
                %inner = calldataload 64
                jnz %inner, @left, @right
            left:
                stop
            right:
                {right_terminator}
            outer_halt:
                mstore 0, %junk
                stop
            }}
        """)
        fn, _, must_halt, _ = _get_stack_cleanup_analyses(ctx)
        asm = VenomCompiler(ctx).generate_evm_assembly(no_optimize=True)
        return fn, must_halt, _block_opcodes(asm, "candidate")

    all_halt_fn, all_halt_regions, all_halt_ops = compile_candidate("stop")
    mixed_fn, mixed_regions, mixed_ops = compile_candidate("ret %retpc")

    assert all_halt_fn.get_basic_block("candidate") in all_halt_regions.must_halt
    assert mixed_fn.get_basic_block("candidate") not in mixed_regions.must_halt
    assert "POP" not in all_halt_ops
    assert "POP" in mixed_ops


@pytest.mark.parametrize("terminator", ["ret 0", "dret 0, 0", "retfmp 0, 0"])
def test_internal_returns_are_not_message_halts(terminator):
    ctx = parse_venom(f"""
        function test {{
        entry:
            {terminator}
        }}
    """)

    fn, _, must_halt, _ = _get_stack_cleanup_analyses(ctx)
    assert fn.entry not in must_halt.must_halt


def test_loop_with_halting_exit_is_not_must_halt():
    ctx = parse_venom("""
        function test {
        entry:
            jmp @loop
        loop:
            jnz 1, @loop, @halt
        halt:
            stop
        }
    """)

    fn, _, must_halt, _ = _get_stack_cleanup_analyses(ctx)
    assert fn.get_basic_block("halt") in must_halt.must_halt
    assert fn.get_basic_block("loop") not in must_halt.must_halt
    assert fn.get_basic_block("entry") not in must_halt.must_halt


def test_must_halt_analysis_is_cached_and_invalidated_with_cfg():
    ctx = parse_venom("""
        function test {
        entry:
            stop
        }
    """)
    fn = ctx.entry_function
    assert fn is not None
    ac = IRAnalysesCache(fn)

    first = ac.request_analysis(MustHaltAnalysis)
    assert ac.request_analysis(MustHaltAnalysis) is first
    assert fn.entry in first.must_halt

    fn.entry.instructions[-1].opcode = "ret"
    ac.invalidate_analysis(CFGAnalysis)

    second = ac.request_analysis(MustHaltAnalysis)
    assert second is not first
    assert fn.entry not in second.must_halt


def test_stack_cleanup_elision_requires_a_known_entry_function():
    ctx = parse_venom("""
        function test {
        entry:
            jnz 1, @halt, @other_halt
        halt:
            stop
        other_halt:
            stop
        }
    """)
    ctx.entry_function = None

    fn, _, must_halt, safety = _get_stack_cleanup_analyses(ctx)
    halt = fn.get_basic_block("halt")
    assert halt in must_halt
    assert not safety.can_skip_cleanup(halt, 0)


def test_stack_bound_rejects_recursive_internal_calls():
    def candidate_is_safe(callee_body):
        ctx = parse_venom(f"""
            function test {{
            entry:
                jnz 1, @candidate, @other
            candidate:
                invoke @callee
                stop
            other:
                stop
            }}

            function callee {{
            callee:
                %retpc = param
                {callee_body}
                ret %retpc
            }}
        """)
        fn, _, must_halt, safety = _get_stack_cleanup_analyses(ctx)
        candidate = fn.get_basic_block("candidate")
        assert candidate in must_halt.must_halt
        return safety.can_skip_cleanup(candidate, 0)

    assert candidate_is_safe("nop")
    assert not candidate_is_safe("invoke @callee")


def test_callee_stack_bound_includes_the_caller_frame():
    ctx = parse_venom("""
        function test {
        entry:
            invoke @callee
            stop
        }

        function callee {
        entry:
            %retpc = param
            jnz 1, @halt, @other_halt
        halt:
            stop
        other_halt:
            stop
        }
    """)
    fn, _, _, safety = _get_stack_cleanup_analyses(ctx, "callee")
    halt = fn.get_basic_block("halt")
    growth = safety._max_growth_from_block(halt, set(), {fn})
    caller_height = safety._max_caller_stack_height(fn, set())

    assert growth is not None
    assert caller_height is not None and caller_height > 0
    safe_height = _EVM_STACK_LIMIT - caller_height - growth
    assert safety.max_safe_current_height(halt) == safe_height
    assert safety.can_skip_cleanup(halt, safe_height)
    assert not safety.can_skip_cleanup(halt, safe_height + 1)


def test_retained_junk_loses_its_identity_before_a_halting_phi_join():
    ctx = parse_venom("""
        function test {
        entry:
            %cond = calldataload 0
            %a = calldataload 32
            %b = calldataload 64
            %c = calldataload 96
            jnz %cond, @p1, @p2
        p1:
            jmp @join
        p2:
            jmp @join
        join:
            %x = phi @p1, %a, @p2, %b
            %y = phi @p1, %a, @p2, %c
            %z = add %x, %y
            mstore 0, %z
            return 0, 32
        }
    """)

    _, _, must_halt, _ = _get_stack_cleanup_analyses(ctx)
    assert {"entry", "p1", "p2", "join"} == {bb.label.value for bb in must_halt.must_halt}

    asm = VenomCompiler(ctx).generate_evm_assembly(no_optimize=True)
    assert "RETURN" in asm


def test_cleanup_falls_back_near_evm_stack_limit():
    ctx = parse_venom("""
        function test {
        entry:
            %junk = calldataload 0
            %cond = calldataload 32
            jnz %cond, @halt, @use_junk
        halt:
            stop
        use_junk:
            mstore 0, %junk
            stop
        }
    """)
    fn, liveness, _, safety = _get_stack_cleanup_analyses(ctx)
    halt = fn.get_basic_block("halt")
    junk = fn.entry.instructions[0].output

    compiler = VenomCompiler(ctx)
    compiler.cfg = liveness.cfg
    compiler.liveness = liveness
    compiler._stack_cleanup_safety = safety

    safe_height = safety.max_safe_current_height(halt)
    assert safe_height is not None

    def stack_at_height(height):
        stack = StackModel()
        for i in range(height - 1):
            stack.push(IRVariable(f"%padding_{i}"))
        stack.push(junk)
        return stack

    safe_stack = stack_at_height(safe_height)
    safe_asm = []
    compiler.clean_stack_from_cfg_in(safe_asm, halt, safe_stack)
    assert safe_asm == []
    assert safe_stack.height == safe_height

    unsafe_stack = stack_at_height(safe_height + 1)
    unsafe_asm = []
    compiler.clean_stack_from_cfg_in(unsafe_asm, halt, unsafe_stack)
    assert unsafe_asm == ["POP"]
    assert unsafe_stack.height == safe_height


def test_retained_values_do_not_desynchronize_recursive_codegen_or_spill_slots():
    loads = "\n".join(f"%v{i} = mload {i * 32}" for i in range(24))
    left_sum = "\n".join(
        ["%a0 = add %v0, %v23"] + [f"%a{i} = add %a{i - 1}, %v{i}" for i in range(1, 12)]
    )
    right_sum = "\n".join(
        ["%b0 = add %v12, %v23"] + [f"%b{i} = add %b{i - 1}, %v{i + 12}" for i in range(1, 11)]
    )
    source = f"""
        function test {{
        entry:
            {loads}
            %cond = mload 800
            jnz %cond, @left, @right
        left:
            {left_sum}
            mstore 0, %a11
            stop
        right:
            {right_sum}
            mstore 0, %b10
            stop
        }}
    """
    spill_base = 0x10000

    def compile_source():
        ctx = parse_venom(source)
        fn = ctx.get_function(IRLabel("test"))
        ctx.mem_allocator.fn_eom[fn] = spill_base
        compiler = VenomCompiler(ctx)
        asm = compiler.generate_evm_assembly(no_optimize=True)
        return compiler, asm

    compiler, asm = compile_source()
    _, second_asm = compile_source()

    assert [str(item) for item in asm] == [str(item) for item in second_asm]
    assert "POP" not in _block_opcodes(asm, "left")
    assert "POP" not in _block_opcodes(asm, "right")
    assert compiler.spiller.peak_spill_end > spill_base

    allocated_slots = set(range(spill_base, compiler.spiller.peak_spill_end, 32))
    free_slots = compiler.spiller._spill_free_slots
    assert set(free_slots) == allocated_slots
    assert len(free_slots) == len(allocated_slots)

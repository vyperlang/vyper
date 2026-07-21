import pytest

from vyper.compiler.settings import OptimizationLevel
from vyper.evm.assembler.instructions import Label
from vyper.venom import generate_assembly_experimental
from vyper.venom.analysis import CFGAnalysis, IRAnalysesCache, LivenessAnalysis, MustHaltAnalysis
from vyper.venom.basicblock import IRLabel
from vyper.venom.context import IRContext
from vyper.venom.parser import parse_venom
from vyper.venom.stack_safety import StackCleanupSafety
from vyper.venom.venom_to_assembly import VenomCompiler


def _get_stack_cleanup_analyses(ctx, fn_name="test"):
    fn = ctx.get_function(IRLabel(fn_name))
    ac = IRAnalysesCache(fn)
    liveness = ac.request_analysis(LivenessAnalysis)
    must_halt = ac.request_analysis(MustHaltAnalysis)
    safety = ac.request_analysis(StackCleanupSafety)
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
    ("terminator", "evm_opcode"),
    [
        ("return 0, 32", "RETURN"),
        ("revert 0, 32", "REVERT"),
        ("stop", "STOP"),
        ("invalid", "INVALID"),
        ("selfdestruct 0", "SELFDESTRUCT"),
    ],
)
def test_direct_and_transitive_message_halts(terminator, evm_opcode):
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
    assert evm_opcode in asm
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
    first_safety = ac.request_analysis(StackCleanupSafety)
    assert ac.request_analysis(MustHaltAnalysis) is first
    assert ac.request_analysis(StackCleanupSafety) is first_safety
    assert fn.entry in first.must_halt

    fn.entry.instructions[-1].opcode = "ret"
    ac.invalidate_analysis(CFGAnalysis)

    second = ac.request_analysis(MustHaltAnalysis)
    second_safety = ac.request_analysis(StackCleanupSafety)
    assert second is not first
    assert second_safety is not first_safety
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


def test_stack_bound_allows_internal_calls():
    ctx = parse_venom("""
        function test {
        entry:
            jnz 1, @candidate, @other
        candidate:
            invoke @callee
            stop
        other:
            stop
        }

        function callee {
        callee:
            %retpc = param
            nop
            ret %retpc
        }
    """)
    fn, _, must_halt, safety = _get_stack_cleanup_analyses(ctx)
    candidate = fn.get_basic_block("candidate")

    assert candidate in must_halt.must_halt
    assert safety.can_skip_cleanup(candidate, 0)


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
    safe_height = safety.max_safe_current_height(halt)

    assert safe_height is not None
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
    fn, _, _, safety = _get_stack_cleanup_analyses(ctx)
    halt = fn.get_basic_block("halt")

    safe_height = safety.max_safe_current_height(halt)
    assert safe_height is not None
    assert safety.can_skip_cleanup(halt, safe_height)
    assert not safety.can_skip_cleanup(halt, safe_height + 1)

    asm = VenomCompiler(ctx).generate_evm_assembly(no_optimize=True)
    assert "POP" not in _block_opcodes(asm, "halt")


def test_cleanup_elision_does_not_induce_spilling():
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
    left_ops = _block_opcodes(asm, "left")
    right_ops = _block_opcodes(asm, "right")

    # Left-path junk is interleaved with live values and is cleaned.  Right-
    # path junk is a harmless bottom prefix and is retained.  Neither path
    # needs the bulk memory spill caused by retaining arbitrary junk.
    assert left_ops.count("POP") > right_ops.count("POP")
    assert compiler.spiller.peak_spill_end == 0

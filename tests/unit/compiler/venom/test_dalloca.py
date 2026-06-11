import pytest
from pyrevm import EVM, AccountInfo

from tests.venom_utils import assert_ctx_eq, find_inst, parse_from_basic_block, run_ssa
from vyper.compiler.settings import OptimizationLevel, VenomOptimizationFlags
from vyper.evm.address_space import MEMORY
from vyper.evm.assembler.core import assembly_to_evm
from vyper.evm.assembler.instructions import CONST
from vyper.evm.opcodes import version_check
from vyper.exceptions import CompilerPanic
from vyper.ir.compile_ir import Label
from vyper.venom import run_passes_on
from vyper.venom.analysis import (
    BasePtrAnalysis,
    DFGAnalysis,
    DominatorTreeAnalysis,
    DynamicMemoryAnalysis,
    IRAnalysesCache,
    LivenessAnalysis,
    LoadAnalysis,
    MemoryAliasAnalysis,
    MemSSA,
    ReadonlyMemoryArgsGlobalAnalysis,
    VarDefinition,
    VariableRangeAnalysis,
)
from vyper.venom.basicblock import IRLabel, IRLiteral, IRVariable
from vyper.venom.call_layout import FunctionCallLayout
from vyper.venom.check_venom import (
    MixedFmpIRError,
    PostLoweringError,
    check_calling_convention,
    find_post_lowering_errors,
)
from vyper.venom.context import IRContext
from vyper.venom.effects import Effects
from vyper.venom.parser import parse_venom
from vyper.venom.passes import (
    CSE,
    CFGNormalization,
    ConcretizeMemLocPass,
    DretDesugarPass,
    FmpLoweringPass,
    RemoveUnusedVariablesPass,
    SimplifyCFGPass,
    SingleUseExpansion,
    fmp_lowering,
)
from vyper.venom.passes.dead_store_elimination import DeadStoreElimination
from vyper.venom.passes.function_inliner import FunctionInlinerPass
from vyper.venom.venom_to_assembly import VenomCompiler


def _apply_dalloca_lowering(fn):
    ConcretizeMemLocPass(IRAnalysesCache(fn), fn).run_pass()
    run_ssa(fn)
    FmpLoweringPass(IRAnalysesCache(fn), fn).run_pass()
    run_ssa(fn)


def _apply_lowering(fn):
    DretDesugarPass(IRAnalysesCache(fn), fn).run_pass()
    _apply_dalloca_lowering(fn)
    SingleUseExpansion(IRAnalysesCache(fn), fn).run_pass()


def _apply_loop_lowering(fn):
    # like _apply_lowering, but with the CFG cleanup the assembler requires
    # for loop-shaped (multi-in/multi-out) basic blocks
    DretDesugarPass(IRAnalysesCache(fn), fn).run_pass()
    _apply_dalloca_lowering(fn)
    SimplifyCFGPass(IRAnalysesCache(fn), fn).run_pass()
    CFGNormalization(IRAnalysesCache(fn), fn).run_pass()
    SingleUseExpansion(IRAnalysesCache(fn), fn).run_pass()


def _execute(bytecode: bytes, calldata: bytes = b"") -> bytes:
    caller = "0x" + "10" * 20
    addr = "0x" + "20" * 20
    evm = EVM()
    evm.set_balance(caller, 1)
    evm.insert_account_info(addr, AccountInfo(code=bytecode))
    return evm.message_call(caller=caller, to=addr, calldata=calldata, gas=1_000_000)


def _run_program(src: str, calldata: bytes = b"", *, lower=_apply_lowering) -> bytes:
    ctx = parse_venom(src)
    for fn in reversed(list(ctx.functions.values())):
        lower(fn)

    asm = VenomCompiler(ctx).generate_evm_assembly()
    bytecode, _ = assembly_to_evm(asm)
    return _execute(bytecode, calldata)


def _run_program_full_pipeline(
    src: str, calldata: bytes = b"", *, disable_inlining: bool
) -> tuple[bytes, IRContext]:
    ctx = parse_venom(src)
    flags = VenomOptimizationFlags(level=OptimizationLevel.O2, disable_inlining=disable_inlining)
    run_passes_on(ctx, flags, disable_mem_checks=True)

    asm = VenomCompiler(ctx).generate_evm_assembly()
    bytecode, _ = assembly_to_evm(asm)
    return _execute(bytecode, calldata), ctx


def _word(out: bytes, idx: int = 0) -> int:
    return int.from_bytes(out[idx * 32 : (idx + 1) * 32], "big")


def test_dalloca_has_no_memory_effects():
    ctx = parse_from_basic_block("""
        main:
            %p = dalloca 32
            sink %p
        """)
    fn = next(iter(ctx.functions.values()))
    inst = fn.entry.instructions[0]

    assert Effects.MEMORY not in inst.get_read_effects()
    assert Effects.MEMORY not in inst.get_write_effects()


def test_dalloca_does_not_crash_memory_dse():
    ctx = parse_from_basic_block("""
        main:
            %p = dalloca 32
            mstore %p, 1
            stop
        """)
    fn = next(iter(ctx.functions.values()))

    DeadStoreElimination(IRAnalysesCache(fn), fn).run_pass(addr_space=MEMORY)


@pytest.mark.parametrize(
    ("calldata", "expected_ptr1", "expected_ptr2"),
    [(b"", 0, 0), (b"x", 0, 32), (b"x" * 31, 0, 32), (b"x" * 32, 0, 32), (b"x" * 33, 0, 64)],
)
def test_dalloca_handles_small_sizes(calldata, expected_ptr1, expected_ptr2):
    out = _run_program(
        """
        function main {
            main:
                %size = calldatasize
                %a = dalloca %size
                %b = dalloca 32
                mstore 0, %a
                mstore 32, %b
                return 0, 64
        }
        """,
        calldata,
    )

    assert _word(out, 0) == expected_ptr1
    assert _word(out, 1) == expected_ptr2


def test_dalloca_static_frame_prime_is_word_aligned():
    out = _run_program("""
        function main {
            main:
                %static = alloca 33
                mstore %static, 0x1111
                %a = dalloca 0
                %b = dalloca 32
                mstore 0, %a
                mstore 32, %b
                return 0, 64
        }
        """)

    assert _word(out, 0) == 64
    assert _word(out, 1) == 64


def test_dalloca_is_fully_lowered():
    ctx = parse_from_basic_block("""
        main:
            %size = calldatasize
            %a = dalloca %size
            %b = dalloca 32
            mstore %a, %b
            stop
    """)
    fn = next(iter(ctx.functions.values()))
    ConcretizeMemLocPass(IRAnalysesCache(fn), fn).run_pass()
    run_ssa(fn)
    FmpLoweringPass(IRAnalysesCache(fn), fn).run_pass()

    opcodes = [inst.opcode for bb in fn.get_basic_blocks() for inst in bb.instructions]
    assert "dalloca" not in opcodes
    assert "bump" in opcodes


def test_dalloca_alignment_mask_uses_small_literal():
    ctx = parse_from_basic_block("""
        main:
            %size = calldatasize
            %p = dalloca %size
            mstore %p, 1
            stop
    """)
    fn = next(iter(ctx.functions.values()))
    ConcretizeMemLocPass(IRAnalysesCache(fn), fn).run_pass()
    run_ssa(fn)
    FmpLoweringPass(IRAnalysesCache(fn), fn).run_pass()

    insts = [inst for bb in fn.get_basic_blocks() for inst in bb.instructions]
    assert any(inst.opcode == "not" and inst.operands == [IRLiteral(31)] for inst in insts)
    assert not any(
        inst.opcode == "and" and any(isinstance(op, IRLiteral) for op in inst.operands)
        for inst in insts
    )


def test_dalloca_lowering_invalidates_stale_analyses():
    ctx = parse_from_basic_block("""
        main:
            %size = calldatasize
            %p = dalloca %size
            mstore %p, 1
            stop
        """)
    fn = next(iter(ctx.functions.values()))
    ConcretizeMemLocPass(IRAnalysesCache(fn), fn).run_pass()
    run_ssa(fn)

    ac = IRAnalysesCache(fn)
    ac.request_analysis(LoadAnalysis)
    ac.request_analysis(MemSSA)
    ac.request_analysis(MemoryAliasAnalysis)
    ac.request_analysis(VarDefinition)
    ac.request_analysis(VariableRangeAnalysis)
    ac.request_analysis(ReadonlyMemoryArgsGlobalAnalysis)

    FmpLoweringPass(ac, fn).run_pass()

    assert LoadAnalysis not in ac.analyses_cache
    assert MemSSA not in ac.analyses_cache
    assert MemoryAliasAnalysis not in ac.analyses_cache
    assert VarDefinition not in ac.analyses_cache
    assert VariableRangeAnalysis not in ac.analyses_cache
    assert ReadonlyMemoryArgsGlobalAnalysis not in ctx.global_analyses_cache.analyses_cache


def test_dalloca_reaching_codegen_panics():
    ctx = parse_venom("""
        function main {
            main:
                %p = dalloca 32
                mstore 0, %p
                return 0, 32
        }
        """)
    with pytest.raises(CompilerPanic, match="dalloca reached codegen"):
        VenomCompiler(ctx).generate_evm_assembly()


def test_dret_reaching_codegen_panics():
    ctx = parse_venom("""
        function main {
            main:
                %retpc = param
                %p = 0
                dret 1, %p, 32, %retpc
        }
        """)
    with pytest.raises(CompilerPanic, match="dret reached codegen"):
        VenomCompiler(ctx).generate_evm_assembly()


def test_auto_reclaim_before_later_allocation_when_dead():
    out = _run_program("""
        function main {
            main:
                %p = dalloca 32
                mstore %p, 7
                %q = dalloca 32
                mstore 0, %q
                return 0, 32
        }
        """)
    assert _word(out) == 0


def test_auto_reclaim_keeps_aliased_live_allocation():
    out = _run_program("""
        function main {
            main:
                %p = dalloca 32
                %alias = %p
                mstore %p, 7
                %q = dalloca 32
                %v = mload %alias
                mstore 0, %q
                mstore 32, %v
                return 0, 64
        }
        """)
    assert _word(out, 0) == 32
    assert _word(out, 1) == 7


def test_auto_reclaim_keeps_pointer_arithmetic_alias_live():
    out = _run_program("""
        function main {
            main:
                %p = dalloca 64
                %q = add 32, %p
                mstore %q, 7
                %r = dalloca 64
                %r_tail = add 32, %r
                mstore %r_tail, 9
                %v = mload %q
                mstore 0, %r
                mstore 32, %v
                return 0, 64
        }
        """)
    assert _word(out, 0) == 64
    assert _word(out, 1) == 7


def test_auto_reclaim_pre_ssa_reassigned_pointer_var_is_conservative():
    out = _run_program(
        """
        function main {
            main:
                %zero = 0
                %p = dalloca 64
                %d = add 32, %p
                mstore %d, 7
                %cond = calldatasize
                jnz %cond, @clobber, @keep

            keep:
                jmp @join

            clobber:
                %d = %zero
                jmp @join

            join:
                %q = dalloca 64
                %q_tail = add 32, %q
                mstore %q_tail, 0xdead
                %v = mload %d
                mstore 0, %q
                mstore 32, %v
                return 0, 64
        }
        """,
        b"",
    )
    assert _word(out, 0) == 64
    assert _word(out, 1) == 7


def test_auto_reclaim_only_dead_lifo_suffix():
    out = _run_program("""
        function main {
            main:
                %a = dalloca 32
                %b = dalloca 32
                mstore %a, 1
                %c = dalloca 32
                mstore %b, 1
                mstore 0, %c
                return 0, 32
        }
        """)
    assert _word(out) == 64


def test_auto_reclaim_across_simple_branches():
    out = _run_program(
        """
        function main {
            main:
                %p = dalloca 32
                %cond = calldatasize
                jnz %cond, @left, @right

            left:
                mstore %p, 11
                jmp @join

            right:
                mstore %p, 22
                jmp @join

            join:
                %q = dalloca 32
                mstore 0, %q
                return 0, 32
        }
        """,
        b"x",
    )
    assert _word(out) == 0


def test_loop_carried_dalloca_threads_fmp_conservatively():
    out, _ = _run_program_full_pipeline(
        """
        function main {
            main:
                %i = 0
                jmp @loop

            loop:
                %p = dalloca 32
                %i = add %i, 1
                %done = eq %i, 2
                jnz %done, @exit, @loop

            exit:
                mstore 0, %p
                return 0, 32
        }
        """,
        disable_inlining=True,
    )
    assert _word(out) == 32


def test_hidden_fmp_output_on_dret_invoke_moves_later_dalloca():
    out = _run_program("""
        function main {
            main:
                %returned = invoke @callee
                %next = dalloca 32
                mstore 0, %returned
                mstore 32, %next
                return 0, 64
        }

        function callee {
            callee:
                %retpc = param
                %p = dalloca 32
                mstore %p, 7
                dret 1, %p, 32, %retpc
        }
        """)
    assert _word(out, 0) == 0
    assert _word(out, 1) == 32


def test_lowered_caller_invokes_untouched_by_fmp_lowering():
    # an already-lowered (annotated) caller's convention is frozen:
    # FmpLoweringPass must leave its shape -- including invoke operands that
    # are NOT hidden FMP operands -- exactly as written.
    ctx = parse_venom("""
        function caller [fmp_lowered] {
            caller:
                %fmp = fmp_param
                %retpc = retpc_param
                %arg = source
                mstore 0, %fmp
                invoke @callee, %arg
                ret %retpc
        }

        function callee {
            callee:
                %retpc = retpc_param
                ret %retpc
        }
    """)

    caller = ctx.get_function(IRLabel("caller"))
    FmpLoweringPass(IRAnalysesCache(caller), caller).run_pass()

    invoke = find_inst(caller, "invoke")
    assert invoke.operands == [IRLabel("callee"), IRVariable("%arg")]


def test_no_ret_function_inserts_hidden_fmp_before_return_pc():
    # An internal function that unconditionally terminates (no `ret`/`dret`,
    # e.g. reverts, self-destructs) still carries a return-PC param. When it needs FMP
    # (here, a dalloca), the hidden FMP param must be inserted *before* the
    # return-PC param and the bump must thread that FMP — not reuse the
    # return-PC value as the allocation base. With no `ret` to anchor it, the
    # return-PC slot is named syntactically by the frontend-emitted
    # `retpc_param` opcode.
    # (A separate entry function keeps `f` non-entry, since the entry
    # function's FMP root is seeded with `initial_fmp` instead of a param.)
    ctx = parse_venom("""
        function main {
            main:
                return 0, 0
        }

        function f {
            f:
                %a = param
                %retpc = retpc_param
                %p = dalloca 64
                mstore %p, %a
                return %p, 64
        }
        """)

    fn = ctx.get_function(IRLabel("f"))

    FmpLoweringPass(IRAnalysesCache(fn), fn).run_pass()

    params = [inst for inst in fn.entry.instructions if inst.is_param]
    # a hidden FMP param was inserted (user, hidden_fmp, return_pc)
    assert [inst.opcode for inst in params] == ["param", "fmp_param", "retpc_param"]
    retpc = IRVariable("%retpc")
    # return-PC param stays last; the inserted hidden FMP sits before it
    assert params[-1].output == retpc
    hidden_fmp = params[1].output
    assert hidden_fmp != retpc

    bump = find_inst(fn, "bump")

    # resolve the bump's FMP operand through any assign chain back to its root
    defs = {
        inst.output: inst
        for bb in fn.get_basic_blocks()
        for inst in bb.instructions
        if inst.num_outputs == 1
    }
    root = bump.operands[0]
    while isinstance(root, IRVariable) and root in defs and defs[root].opcode == "assign":
        root = defs[root].operands[0]

    # the FMP base must be the inserted hidden FMP param, never the return PC
    assert root == hidden_fmp
    assert root != retpc


def test_parser_reconstructs_signature_from_annotation_and_opcodes():
    # parsed lowered IR is self-describing: `publishes` comes from the
    # `fmp_publishes` annotation token, `has_fmp_param` from the presence of
    # the `fmp_param` opcode -- nothing is inferred from shapes or arities.
    ctx = parse_venom("""
        function f [fmp_lowered] {
            f:
                %user = param
                %fmp = fmp_param
                %ret_pc = retpc_param
                %p, %next = bump 32, %fmp
                mstore %p, %user
                ret %ret_pc, %p
        }
        """)
    fn = ctx.get_function(IRLabel("f"))
    sig = fn._fmp_signature
    assert sig is not None
    assert sig.has_fmp_param is True
    assert sig.publishes is False

    layout = FunctionCallLayout(fn)
    assert layout.has_physical_hidden_fmp_param is True
    assert [inst.output for inst in layout.user_params] == [IRVariable("%user")]
    assert layout.expected_user_arg_count == 1


def test_parser_leaves_raw_functions_unsealed():
    # control: an un-annotated (raw) function gets no signature; its
    # convention is materialized later by FmpLoweringPass
    ctx = parse_venom("""
        function f {
            f:
                %user = param
                %ret_pc = param
                ret %ret_pc, %user
        }
        """)
    fn = ctx.get_function(IRLabel("f"))
    assert fn._fmp_signature is None
    # raw-level definition: the ret anchors the return-PC param
    layout = FunctionCallLayout(fn)
    assert layout.return_pc_param is not None
    assert layout.return_pc_param.output == IRVariable("%ret_pc")
    assert layout.expected_user_arg_count == 1


def test_dret_desugar_ignores_dalloca_only_callee():
    ctx = parse_venom("""
        function main {
            main:
                invoke @callee
                return 0, 0
        }

        function callee {
            callee:
                %retpc = param
                %p = dalloca 32
                ret %retpc
        }
    """)

    fn = ctx.entry_function
    DretDesugarPass(IRAnalysesCache(fn), fn).run_pass()

    params = [inst for inst in fn.entry.instructions if inst.opcode == "param"]
    assert params == []

    invoke = find_inst(fn, "invoke")
    assert invoke.operands == [IRLabel("callee")]


def test_get_transitive_uses_handles_multi_output_bump():
    # Regression: DFGAnalysis.get_transitive_uses walked only `.output`, which
    # asserts a single output. `bump` (the lowered form of `dalloca`) has two
    # outputs, so taking transitive uses of a bump must not crash.
    ctx = parse_venom("""
        function main {
            main:
                %p = dalloca 64
                %q = add 32, %p
                mstore %q, 7
                return %p, 64
        }
        """)
    fn = ctx.get_function(IRLabel("main"))
    _apply_lowering(fn)

    bump = find_inst(fn, "bump")

    dfg = IRAnalysesCache(fn).request_analysis(DFGAnalysis)
    uses = dfg.get_transitive_uses(bump)  # must not raise on the 2-output bump

    assert bump in uses
    # the pointer output feeds `add %q`, reachable transitively from the bump
    assert any(inst.opcode == "add" for inst in uses)


def test_dret_desugar_with_ordinary_return_and_dynamic_buffer():
    out = _run_program("""
        function main {
            main:
                %ordinary, %ptr = invoke @callee
                %v = mload %ptr
                mstore 0, %ordinary
                mstore 32, %v
                return 0, 64
        }

        function callee {
            callee:
                %retpc = param
                %p = dalloca 32
                mstore %p, 0x1234
                dret 1, 99, %p, 32, %retpc
        }
        """)
    assert _word(out, 0) == 99
    assert _word(out, 1) == 0x1234


def test_dret_desugar_with_multiple_dynamic_buffers():
    out = _run_program("""
        function main {
            main:
                %a, %b = invoke @callee
                %va = mload %a
                %vb = mload %b
                mstore 0, %a
                mstore 32, %b
                mstore 64, %va
                mstore 96, %vb
                return 0, 128
        }

        function callee {
            callee:
                %retpc = param
                %a = dalloca 32
                %b = dalloca 32
                mstore %a, 11
                mstore %b, 22
                dret 2, %a, 32, %b, 32, %retpc
        }
        """)
    assert _word(out, 0) == 0
    assert _word(out, 1) == 32
    assert _word(out, 2) == 11
    assert _word(out, 3) == 22


def test_dret_bad_return_order_can_clobber_later_source():
    out = _run_program("""
        function main {
            main:
                %a, %b = invoke @callee
                %va = mload %a
                %vb = mload %b
                mstore 0, %va
                mstore 32, %vb
                return 0, 64
        }

        function callee {
            callee:
                %retpc = param
                %a = dalloca 32
                %b = dalloca 32
                mstore %a, 11
                mstore %b, 22
                dret 2, %b, 32, %a, 32, %retpc
        }
        """)
    assert _word(out, 0) == 22
    assert _word(out, 1) == 22


@pytest.mark.parametrize(("calldata", "expected_next"), [(b"", 0), (b"x" * 33, 64)])
def test_dret_supports_zero_and_runtime_sizes(calldata, expected_next):
    out = _run_program(
        """
        function main {
            main:
                %returned = invoke @callee
                %next = dalloca 32
                mstore 0, %returned
                mstore 32, %next
                return 0, 64
        }

        function callee {
            callee:
                %retpc = param
                %size = calldatasize
                %p = dalloca 64
                mstore %p, 7
                dret 1, %p, %size, %retpc
        }
        """,
        calldata,
    )
    assert _word(out, 0) == 0
    assert _word(out, 1) == expected_next


def test_dret_pre_cancun_copy_path(monkeypatch):
    monkeypatch.setattr(fmp_lowering, "version_check", lambda **kwargs: False)
    ctx = parse_venom("""
        function callee {
            callee:
                %retpc = param
                %p = dalloca 32
                dret 1, %p, 32, %retpc
        }
    """)
    fn = ctx.get_function(IRLabel("callee"))
    DretDesugarPass(IRAnalysesCache(fn), fn).run_pass()

    opcodes = [inst.opcode for bb in fn.get_basic_blocks() for inst in bb.instructions]
    assert "mcopy" not in opcodes
    assert "staticcall" in opcodes
    assert "assert" in opcodes

    out = _run_program(
        """
        function main {
            main:
                %returned = invoke @callee
                %v = mload %returned
                mstore 0, %v
                return 0, 32
        }

        function callee {
            callee:
                %retpc = param
                %size = calldatasize
                %p = dalloca 64
                mstore %p, 7
                dret 1, %p, %size, %retpc
        }
        """,
        b"x" * 33,
    )
    assert _word(out) == 7


def test_dret_full_pipeline_with_and_without_inlining():
    src = """
    function main {
        main:
            %ptr = invoke @callee
            %v = mload %ptr
            mstore 0, %v
            return 0, 32
    }

    function callee {
        callee:
            %retpc = param
            %p = dalloca 32
            mstore %p, 123
            dret 1, %p, 32, %retpc
    }
    """

    out_inlined, ctx_inlined = _run_program_full_pipeline(src, disable_inlining=False)
    out_no_inline, _ = _run_program_full_pipeline(src, disable_inlining=True)

    assert _word(out_inlined) == 123
    assert out_inlined == out_no_inline
    assert IRLabel("callee") not in ctx_inlined.functions


def test_dret_adopted_fmp_flows_to_later_non_inlined_callee():
    out, _ = _run_program_full_pipeline(
        """
        function main {
            main:
                %ptr = invoke @producer
                jmp @join

            join:
                invoke @scratch
                %v = mload %ptr
                mstore 0, %v
                return 0, 32
        }

        function producer {
            producer:
                %retpc = param
                %p = dalloca 32
                mstore %p, 0x1234
                dret 1, %p, 32, %retpc
        }

        function scratch {
            scratch:
                %retpc = param
                %q = dalloca 32
                mstore %q, 0xdead
                ret %retpc
        }
        """,
        disable_inlining=True,
    )

    assert _word(out) == 0x1234


def test_unreachable_raw_dret_does_not_block_inlining():
    ctx = parse_venom("""
        function main {
            main:
                return 0, 0
        }

        function dead {
            dead:
                %retpc = param
                %p = dalloca 32
                dret 1, %p, 32, %retpc
        }
        """)
    flags = VenomOptimizationFlags(level=OptimizationLevel.O2, disable_inlining=False)

    run_passes_on(ctx, flags, disable_mem_checks=True)

    assert IRLabel("dead") not in ctx.functions


# caller allocates before invoking a dret callee. DretDesugarPass touches no
# invokes, so FmpLoweringPass is the sole writer of the hidden FMP operand
# and appends the *threaded* FMP (past the caller's dalloca). A stale
# entry-FMP operand would let the callee pack its dret data over the caller's
# live buffer.
_STALE_INVOKE_FMP_SRC = """
function main {
    main:
        %a = dalloca 32
        mstore %a, 5
        %ptr = invoke @dret_callee
        %v = mload %a
        %w = mload %ptr
        mstore 0, %v
        mstore 32, %w
        return 0, 64
}

function dret_callee {
    dret_callee:
        %retpc = param
        %p = dalloca 32
        mstore %p, 7
        dret 1, %p, 32, %retpc
}
"""


def test_invoke_hidden_fmp_operand_rewritten_after_caller_dalloca():
    out = _run_program(_STALE_INVOKE_FMP_SRC)
    assert _word(out, 0) == 5
    assert _word(out, 1) == 7

    out, _ = _run_program_full_pipeline(_STALE_INVOKE_FMP_SRC, disable_inlining=True)
    assert _word(out, 0) == 5
    assert _word(out, 1) == 7


def test_invoke_hidden_fmp_operand_rewritten_after_caller_dalloca_inlined():
    # structural acceptance criterion for the FMP-virtual-register redesign:
    # with DretDesugarPass the inlined callee's pack addresses root at a
    # cloned `getfmp`, which FmpLoweringPass threads to the post-bump FMP
    # of the host -- there is no stale entry-FMP operand left to consume.
    out, _ = _run_program_full_pipeline(_STALE_INVOKE_FMP_SRC, disable_inlining=False)
    assert _word(out, 0) == 5
    assert _word(out, 1) == 7


def test_auto_reclaim_suppressed_for_live_allocation_dropped_at_merge():
    # One arm of the branch allocates %p2 on top of %p1; the join's meet
    # drops %p2 from the allocation stack (divergent stacks), but %p2 stays
    # live through the phi %p3. Reclaiming %p1's (dead) mark at %p4 would
    # rewind the FMP below %p2, so %p4's tail write would clobber it.
    src = """
    function main {
        main:
            %z = 0
            %p1 = dalloca 32
            mstore %p1, 1
            %cond = calldatasize
            jnz %cond, @a, @b

        a:
            %p2 = dalloca 32
            mstore %p2, 777
            jmp @join

        b:
            jmp @join

        join:
            %p3 = phi @a, %p2, @b, %z
            %v1 = mload %p1
            %p4 = dalloca 64
            %p4_tail = add 32, %p4
            mstore %p4_tail, 999
            %v = mload %p3
            mstore 0, %v
            return 0, 32
    }
    """
    out = _run_program(src, b"x")
    assert _word(out) == 777

    out, _ = _run_program_full_pipeline(src, calldata=b"x", disable_inlining=True)
    assert _word(out) == 777


def test_no_reclaim_for_pointer_escaping_through_memory():
    # %x's pointer escapes SSA tracking by being stored (as a value) into a
    # static slot, then is reloaded through an optimizer-opaque address.
    # Reclaiming %x at %q's allocation would let %q overwrite memory that is
    # still reachable through the slot.
    out = _run_program(
        """
        function main {
            main:
                %slot = alloca 32
                %x = dalloca 32
                mstore %x, 7
                mstore %slot, %x
                %q = dalloca 32
                mstore %q, 0xdead
                %opaque = calldataload 0
                %addr = add %slot, %opaque
                %xptr = mload %addr
                %v = mload %xptr
                mstore 0, %v
                return 0, 32
        }
        """,
        (0).to_bytes(32, "big"),
    )
    assert _word(out) == 7


def test_dret_must_be_desugared_before_inlining():
    ctx = parse_venom("""
        function main {
            main:
                %ptr = invoke @callee
                sink %ptr
        }

        function callee {
            callee:
                %retpc = param
                %p = dalloca 32
                dret 1, %p, 32, %retpc
        }
        """)
    analyses = {fn: IRAnalysesCache(fn) for fn in ctx.functions.values()}
    with pytest.raises(CompilerPanic, match="DretDesugarPass must run before"):
        FunctionInlinerPass(analyses, ctx, VenomOptimizationFlags()).run_pass()


def test_dret_desugar_shape_is_purely_local():
    # DretDesugarPass rewrites only the dret function itself:
    # dret -> getfmp at entry, dst chain, pack copies, setfmp, retfmp.
    # No params are conjured and no invokes are augmented anywhere.
    ctx = parse_venom("""
        function main {
            main:
                %a = dalloca 32
                %ptr = invoke @callee
                mstore 0, %ptr
                return 0, 32
        }

        function callee {
            callee:
                %retpc = param
                %p = dalloca 32
                mstore %p, 7
                dret 1, %p, 32, %retpc
        }
        """)

    for fn in ctx.functions.values():
        DretDesugarPass(IRAnalysesCache(fn), fn).run_pass()

    # caller untouched: no params, invoke not augmented
    main = ctx.get_function(IRLabel("main"))
    main_params = [inst for inst in main.entry.instructions if inst.opcode == "param"]
    assert main_params == []
    invoke = find_inst(main, "invoke")
    assert invoke.operands == [IRLabel("callee")]
    main_opcodes = [inst.opcode for bb in main.get_basic_blocks() for inst in bb.instructions]
    assert "getfmp" not in main_opcodes and "setfmp" not in main_opcodes

    # callee desugared: no dret, no new params; getfmp right after the params
    callee = ctx.get_function(IRLabel("callee"))
    callee_params = [inst for inst in callee.entry.instructions if inst.opcode == "param"]
    assert [p.output for p in callee_params] == [IRVariable("%retpc")]
    assert callee.entry.instructions[len(callee_params)].opcode == "getfmp"

    callee_insts = [inst for bb in callee.get_basic_blocks() for inst in bb.instructions]
    callee_opcodes = [inst.opcode for inst in callee_insts]
    assert "dret" not in callee_opcodes
    # the pack copy: mcopy on cancun+, identity-precompile staticcall before
    if version_check(begin="cancun"):
        assert "mcopy" in callee_opcodes
    else:
        assert "staticcall" in callee_opcodes
    # setfmp directly precedes the retfmp terminator
    assert callee_opcodes[-2:] == ["setfmp", "retfmp"]

    # retfmp returns the pack dst (rooted at the entry getfmp) plus return PC
    retfmp = callee_insts[-1]
    entry_fmp = callee.entry.instructions[len(callee_params)].output
    assert retfmp.operands == [entry_fmp, IRVariable("%retpc")]
    # setfmp advances over the packed data; its operand is not the entry FMP
    setfmp = callee_insts[-2]
    assert setfmp.operands != [entry_fmp]

    # the desugared (half-lowered) IR still validates as input IR
    check_calling_convention(ctx)


def test_inlined_publishing_callee_host_does_not_publish():
    # `retfmp` maps like `ret` in the inliner: values assigned to the
    # call-site outputs, jmp to the continuation, no FMP restore. The host's
    # publish status is determined by the HOST's own terminators: after
    # inlining a publishing callee, a plain-ret host does NOT publish.
    src = """
    function main {
        main:
            %v1 = invoke @host
            %v2 = invoke @host
            mstore 0, %v1
            mstore 32, %v2
            return 0, 64
    }

    function host {
        host:
            %retpc = param
            %ptr = invoke @callee
            %v = mload %ptr
            ret %retpc, %v
    }

    function callee {
        callee:
            %retpc = param
            %p = dalloca 32
            mstore %p, 123
            dret 1, %p, 32, %retpc
    }
    """

    ctx = parse_venom(src)
    for fn in ctx.functions.values():
        DretDesugarPass(IRAnalysesCache(fn), fn).run_pass()

    analyses = {fn: IRAnalysesCache(fn) for fn in ctx.functions.values()}
    # callee has a single call site and gets inlined into host; host has two
    # call sites and survives (threshold 0 blocks size-based inlining)
    flags = VenomOptimizationFlags(inline_threshold=0)
    FunctionInlinerPass(analyses, ctx, flags).run_pass()
    assert IRLabel("callee") not in ctx.functions

    host = ctx.get_function(IRLabel("host"))
    host_opcodes = [inst.opcode for bb in host.get_basic_blocks() for inst in bb.instructions]
    # the cloned FMP register ops are plain instructions in the host body...
    assert "getfmp" in host_opcodes
    assert "setfmp" in host_opcodes
    assert "dalloca" in host_opcodes
    # ...but the host's terminators stay plain `ret`: no publish
    assert "retfmp" not in host_opcodes

    dynamic_memory = IRAnalysesCache(host).request_analysis(DynamicMemoryAnalysis)
    info = dynamic_memory.get_info(host)
    assert info.publishes is False
    assert info.needs_fmp is True

    # end-to-end execution equivalence, inlined and not
    out_inlined, _ = _run_program_full_pipeline(src, disable_inlining=False)
    out_no_inline, _ = _run_program_full_pipeline(src, disable_inlining=True)
    assert _word(out_inlined, 0) == 123
    assert _word(out_inlined, 1) == 123
    assert out_inlined == out_no_inline


def test_getfmp_cse_merges_only_without_intervening_fmp_write():
    # two getfmps with no FMP write in between may merge; a getfmp after an
    # FMP write (dalloca or setfmp) must not be merged with one before it.
    ctx = parse_from_basic_block("""
        main:
            %a = getfmp
            %b = getfmp
            %p = dalloca 32
            %c = getfmp
            sink %a, %b, %c, %p
        """)
    fn = next(iter(ctx.functions.values()))
    CSE(IRAnalysesCache(fn), fn).run_pass()

    insts = {inst.output: inst for inst in fn.entry.instructions if inst.num_outputs == 1}
    # %b merged into %a
    assert insts[IRVariable("%b")].opcode == "assign"
    assert insts[IRVariable("%b")].operands == [IRVariable("%a")]
    # %c not merged: dalloca wrote the FMP register
    assert insts[IRVariable("%c")].opcode == "getfmp"


def test_getfmp_cse_blocked_across_setfmp():
    ctx = parse_from_basic_block("""
        main:
            %a = getfmp
            setfmp 64
            %b = getfmp
            sink %a, %b
        """)
    fn = next(iter(ctx.functions.values()))
    CSE(IRAnalysesCache(fn), fn).run_pass()

    insts = {inst.output: inst for inst in fn.entry.instructions if inst.num_outputs == 1}
    assert insts[IRVariable("%b")].opcode == "getfmp"


def test_setfmp_not_removed_as_unused():
    # setfmp has no outputs and is volatile: DCE-style passes must keep it
    # (and the chain feeding its operand).
    ctx = parse_from_basic_block("""
        main:
            %e = getfmp
            %new = add 32, %e
            setfmp %new
            stop
        """)
    fn = next(iter(ctx.functions.values()))
    RemoveUnusedVariablesPass(IRAnalysesCache(fn), fn).run_pass()

    opcodes = [inst.opcode for inst in fn.entry.instructions]
    assert "setfmp" in opcodes
    assert "getfmp" in opcodes
    assert "add" in opcodes


def test_fmp_register_ops_parser_round_trip():
    src = """
    function main {
        main:
            %retpc = param
            %e = getfmp
            %p = dalloca 32
            setfmp %e
            retfmp 1, %p, %retpc
    }
    """
    ctx = parse_venom(src)
    check_calling_convention(ctx)

    fn = ctx.get_function(IRLabel("main"))
    insts = {inst.opcode: inst for inst in fn.entry.instructions}
    # retfmp follows dret's text convention: operands are NOT reversed
    assert insts["retfmp"].operands == [IRLiteral(1), IRVariable("%p"), IRVariable("%retpc")]
    assert insts["setfmp"].operands == [IRVariable("%e")]
    assert insts["getfmp"].operands == []
    assert insts["getfmp"].output == IRVariable("%e")

    # printer/parser round trip preserves shape
    assert_ctx_eq(ctx, parse_venom(str(ctx)))


def test_fmp_register_ops_reaching_codegen_panic():
    for body in ("%e = getfmp\n                stop", "setfmp 64\n                stop"):
        ctx = parse_venom(f"""
            function main {{
                main:
                    {body}
            }}
            """)
        with pytest.raises(CompilerPanic, match="reached codegen"):
            VenomCompiler(ctx).generate_evm_assembly()


# ---------------------------------------------------------------------------
# Stage 2: single-owner FmpLoweringPass, fmp_param/retpc_param opcodes,
# initial_fmp entry seeding, FmpPrunePass sealing, post-lowering checks.
# ---------------------------------------------------------------------------


def test_fmp_param_retpc_param_round_trip():
    # the dedicated param opcodes and the function-header annotation carry
    # the layout syntactically and round-trip through the printer
    src = """
    function main {
        main:
            stop
    }

    function f [fmp_lowered] {
        f:
            %user = param
            %fmp = fmp_param
            %retpc = retpc_param
            %p, %next = bump 32, %fmp
            mstore %p, %user
            ret %retpc, %p
    }
    """
    ctx = parse_venom(src)
    check_calling_convention(ctx)

    fn = ctx.get_function(IRLabel("f"))
    # syntactic layout: one user param; fmp/retpc named by opcode
    layout = FunctionCallLayout(fn)
    assert layout.expected_user_arg_count == 1
    assert layout.has_physical_hidden_fmp_param
    assert layout.hidden_fmp_param.output == IRVariable("%fmp")
    assert layout.return_pc_param.output == IRVariable("%retpc")
    assert [inst.output for inst in layout.user_params] == [IRVariable("%user")]

    # printer/parser round trip preserves shape (including the annotation:
    # assert_fn_eq compares the reconstructed fmp_signature)
    assert_ctx_eq(ctx, parse_venom(str(ctx)))


def test_entry_function_seeds_initial_fmp_no_prelude():
    # the entry function's FMP root is an explicit `initial_fmp` instruction
    # (lowered to the deferred __initial_fmp__ CONST); the assembler entry
    # prelude special case is gone, so the assembly starts with the CONST
    # declaration followed directly by the entry label.
    src = """
    function main {
        main:
            %p = dalloca 32
            mstore %p, 7
            %v = mload %p
            mstore 0, %v
            return 0, 32
    }
    """
    ctx = parse_venom(src)
    flags = VenomOptimizationFlags(level=OptimizationLevel.O2, disable_inlining=True)
    run_passes_on(ctx, flags, disable_mem_checks=True)

    main = ctx.entry_function
    main_insts = [inst for bb in main.get_basic_blocks() for inst in bb.instructions]
    opcodes = [inst.opcode for inst in main_insts]
    assert "initial_fmp" in opcodes
    # the entry function gets no hidden param
    assert not any(inst.is_param for inst in main.entry.instructions)

    asm = VenomCompiler(ctx).generate_evm_assembly(no_optimize=True)
    assert isinstance(asm[0], CONST)
    assert asm[0].name == "__initial_fmp__"
    # no prelude PUSH between the CONST declaration and the entry label
    assert isinstance(asm[1], Label)

    bytecode, _ = assembly_to_evm(asm)
    out = _execute(bytecode)
    assert _word(out) == 7


def test_fmp_prune_seals_signature_and_callers_see_final_shape():
    # callee's dalloca dies in the optimization tail; FmpPrunePass deletes
    # the fmp_param chain and seals the signature BEFORE main is lowered, so
    # main's invoke is never augmented with a (stale) hidden FMP operand.
    out, ctx = _run_program_full_pipeline(
        """
        function main {
            main:
                %p = dalloca 32
                mstore %p, 5
                invoke @callee
                %v = mload %p
                mstore 0, %v
                return 0, 32
        }

        function callee {
            callee:
                %retpc = param
                %q = dalloca 32
                ret %retpc
        }
        """,
        disable_inlining=True,
    )
    assert _word(out) == 5

    callee = ctx.get_function(IRLabel("callee"))
    dynamic_memory = IRAnalysesCache(callee).request_analysis(DynamicMemoryAnalysis)
    assert not dynamic_memory.function_needs_fmp(callee)

    sig = callee._fmp_signature
    assert sig is not None
    assert sig.has_fmp_param is False
    assert sig.publishes is False
    callee_opcodes = [inst.opcode for bb in callee.get_basic_blocks() for inst in bb.instructions]
    assert "fmp_param" not in callee_opcodes

    main = ctx.get_function(IRLabel("main"))
    invoke = find_inst(main, "invoke")
    assert invoke.operands == [IRLabel("callee")]


_NEVER_RETURNING_FORWARDER_SRC = """
function main {
    main:
        invoke @fwd, 60
        return 0, 0
}

function fwd {
    fwd:
        %a = param
        %ptr = invoke @producer
        %v = mload %ptr
        mstore %a, %v
        return %a, 32
}

function producer {
    producer:
        %retpc = param
        %p = dalloca 32
        mstore %p, 7
        dret 1, %p, 32, %retpc
}
"""


def _assert_single_fmp_param_layout(fwd):
    params = [inst for inst in fwd.entry.instructions if inst.is_param]
    # exactly one hidden FMP param, placed after the user params and before
    # the return-PC param (the last, top-of-stack slot)
    assert [inst.opcode for inst in params] == ["param", "fmp_param", "retpc_param"]


def test_metadata_less_never_returning_forwarder_no_duplicate_fmp_param():
    # Stage-0 minor bug 5 regression: a never-returning forwarder (no `ret`
    # to anchor the return-PC param) used to get a SECOND hidden FMP param
    # from the old second lowering run, whose heuristics could not rediscover
    # the first one. With the single-owner FmpLoweringPass (one run, the
    # run-2 slot is the deletion-only FmpPrunePass) and the syntactic
    # `fmp_param` opcode this is impossible by construction.

    # variant 1: hand-written raw IR with only plain params. Neither the
    # ret-anchored discovery (no `ret`) nor a `retpc_param` opcode names the
    # return-PC slot. Input validation counts every plain param of a
    # never-returning callee as a caller-pushed user arg, so FmpLoweringPass
    # SYNTHESIZES the return-PC name for the unnamed top-of-stack slot --
    # renaming a plain param instead would shrink the user-arg count and
    # panic on validated callers (final-review regression).
    ctx = parse_venom(_NEVER_RETURNING_FORWARDER_SRC)
    check_calling_convention(ctx)  # the shape must be validator-accepted
    for fn in reversed(list(ctx.functions.values())):
        _apply_lowering(fn)
    _assert_single_fmp_param_layout(ctx.get_function(IRLabel("fwd")))

    asm = VenomCompiler(ctx).generate_evm_assembly()
    bytecode, _ = assembly_to_evm(asm)
    out = _execute(bytecode)
    assert _word(out) == 7

    # variant 2: full O2 pipeline on frontend-realistic raw IR -- the
    # frontend names the return-PC slot with the dedicated `retpc_param`
    # opcode, so even a no-ret function is self-describing.
    src = _NEVER_RETURNING_FORWARDER_SRC.replace(
        "%a = param", "%a = param\n        %retpc = retpc_param"
    )
    ctx = parse_venom(src)
    flags = VenomOptimizationFlags(level=OptimizationLevel.O2, disable_inlining=True)
    run_passes_on(ctx, flags, disable_mem_checks=True)
    _assert_single_fmp_param_layout(ctx.get_function(IRLabel("fwd")))

    asm = VenomCompiler(ctx).generate_evm_assembly()
    bytecode, _ = assembly_to_evm(asm)
    out = _execute(bytecode)
    assert _word(out) == 7


def test_post_lowering_check_fires_on_corrupted_shape():
    # corrupting the lowered IR after the pipeline (deleting the hidden FMP
    # operand of an invoke) must be caught by the signature-vs-shape checks
    src = """
    function main {
        main:
            %p = dalloca 32
            mstore %p, 5
            invoke @callee
            return 0, 32
    }

    function callee {
        callee:
            %retpc = param
            %q = dalloca 32
            mstore %q, 9
            log 0, %q, 32
            ret %retpc
    }
    """
    ctx = parse_venom(src)
    flags = VenomOptimizationFlags(level=OptimizationLevel.O2, disable_inlining=True)
    run_passes_on(ctx, flags, disable_mem_checks=True)
    assert find_post_lowering_errors(ctx) == []

    main = ctx.get_function(IRLabel("main"))
    invoke = find_inst(main, "invoke")
    # callee kept its fmp_param (the allocation is observable via log)
    callee = ctx.get_function(IRLabel("callee"))
    assert callee._fmp_signature is not None and callee._fmp_signature.has_fmp_param
    assert len(invoke.operands) == 2  # [target, hidden fmp]

    # corruption 1: drop the hidden operand
    dropped = invoke.operands.pop()
    errors = find_post_lowering_errors(ctx)
    assert any(isinstance(err, PostLoweringError) for err in errors)
    invoke.operands.append(dropped)
    assert find_post_lowering_errors(ctx) == []

    # corruption 2: replace the hidden operand with a non-FMP-rooted value
    invoke.operands[-1] = IRLiteral(0x1234)
    errors = find_post_lowering_errors(ctx)
    assert any(isinstance(err, PostLoweringError) for err in errors)

    # corruption 3: delete the callee's fmp_param (shape no longer matches
    # the frozen signature)
    invoke.operands[-1] = dropped
    fmp_param = next(inst for inst in callee.entry.instructions if inst.opcode == "fmp_param")
    callee.entry.remove_instruction(fmp_param)
    errors = find_post_lowering_errors(ctx)
    assert any(isinstance(err, PostLoweringError) for err in errors)


# ---------------------------------------------------------------------------
# Stage 3: principled reclaim engine -- top-segment-meet dataflow fixpoint,
# single _step interpreter, getfmp capture veto, restore-dominance assertion.
# ---------------------------------------------------------------------------


def test_loop_dalloca_reclaimed_each_iteration():
    # a dalloca that dies within the loop body is reclaimed at the back
    # edge every iteration: the FMP does not grow with the trip count, and
    # the post-loop allocation lands back at the base address.
    src = """
    function main {
        main:
            %i = 0
            jmp @loop

        loop:
            %p = dalloca 32
            mstore %p, %i
            %i = add %i, 1
            %done = eq %i, 2
            jnz %done, @exit, @loop

        exit:
            %q = dalloca 32
            mstore 0, %q
            return 0, 32
    }
    """
    out = _run_program(src, lower=_apply_loop_lowering)
    assert _word(out) == 0  # 64 if the loop leaked one buffer per iteration

    out, _ = _run_program_full_pipeline(src, disable_inlining=True)
    assert _word(out) == 0

    # IR-level: the back-edge reclaim is a restore of %p's mark in the loop
    # body (the bump pointer output assigned back into the FMP runner)
    ctx = parse_venom(src)
    fn = ctx.get_function(IRLabel("main"))
    _apply_dalloca_lowering(fn)
    loop_insts = fn.get_basic_block("loop").instructions
    p_bump = next(inst for inst in loop_insts if inst.opcode == "bump")
    restores = [
        inst
        for inst in loop_insts
        if inst.opcode == "assign" and inst.operands == [p_bump.get_outputs()[0]]
    ]
    assert len(restores) == 1


def test_loop_carried_live_dalloca_not_reclaimed():
    # negative: a loop-carried live pointer (previous iteration's buffer
    # read by the next iteration) blocks per-iteration reclaim. The meet at
    # the loop header drops the live mark (sound: untracked allocations are
    # never reclaimed), so each iteration's buffer stays intact and the FMP
    # grows monotonically.
    out = _run_program(
        """
        function main {
            main:
                %prev = 0
                %i = 0
                jmp @loop

            loop:
                %p = dalloca 32
                mstore %p, 777
                %junk = mload %prev
                %prev = %p
                %i = add %i, 1
                %done = eq %i, 2
                jnz %done, @exit, @loop

            exit:
                %v = mload %prev
                %q = dalloca 32
                mstore 0, %q
                mstore 32, %v
                return 0, 64
        }
        """,
        lower=_apply_loop_lowering,
    )
    # iteration 2's buffer sits at 32: iteration 1's buffer was not
    # reclaimed under it. (%q == 32: the final buffer itself is dead after
    # the exit-block load and is legitimately reclaimed there.)
    assert _word(out, 0) == 32
    assert _word(out, 1) == 777


@pytest.mark.parametrize(("calldata", "expected_q", "expected_vx"), [(b"x", 0, 9), (b"", 0, 0)])
def test_reclaim_fires_across_join_with_agreeing_top_segment(calldata, expected_q, expected_vx):
    # precision: one arm allocates a scratch buffer that dies before the
    # join (popped at the arm's terminator), so all predecessors agree on
    # the surviving top segment [%m]. The meet keeps %m and the reclaim
    # fires after the join -- the engine is not all-or-nothing at merges.
    out = _run_program(
        """
        function main {
            main:
                %m = dalloca 32
                mstore %m, 7
                %vx = 0
                %cond = calldatasize
                jnz %cond, @a, @b

            a:
                %x = dalloca 32
                mstore %x, 9
                %vx = mload %x
                jmp @join

            b:
                jmp @join

            join:
                %vm = mload %m
                %q = dalloca 32
                mstore 0, %q
                mstore 32, %vm
                mstore 64, %vx
                return 0, 96
        }
        """,
        calldata,
    )
    assert _word(out, 0) == expected_q  # %m's mark survived the join and was reclaimed
    assert _word(out, 1) == 7
    assert _word(out, 2) == expected_vx


def test_getfmp_capture_blocks_reclaim_while_live():
    # %e captures the FMP at 0 (where %p is then allocated). While %e is
    # live, popping %p would let %q reuse address 0 and clobber the memory
    # %e still addresses -- the capture vetoes the reclaim.
    out = _run_program("""
        function main {
            main:
                %e = getfmp
                %p = dalloca 32
                mstore %p, 5
                %v = mload %p
                %q = dalloca 32
                mstore %q, 6
                %w = mload %e
                mstore 0, %q
                mstore 32, %w
                mstore 64, %v
                return 0, 96
        }
        """)
    assert _word(out, 0) == 32  # %q did not reuse %p's address
    assert _word(out, 1) == 5  # the capture still sees %p's data
    assert _word(out, 2) == 5


def test_getfmp_capture_allows_reclaim_after_death():
    # once the capture (and everything derived from it) is dead, it no
    # longer vetoes: the dead %p is reclaimed and %q reuses its address.
    out = _run_program("""
        function main {
            main:
                %e = getfmp
                %junk = mload %e
                %p = dalloca 32
                mstore %p, 5
                %v = mload %p
                %q = dalloca 32
                mstore 0, %q
                mstore 32, %v
                return 0, 64
        }
        """)
    assert _word(out, 0) == 0  # %p reclaimed; %q reuses the base address
    assert _word(out, 1) == 5


def test_escaped_getfmp_capture_pins_reclaim():
    # the capture escapes SSA tracking (stored to memory as a value), so
    # derived pointers can re-enter where liveness cannot see them: the
    # capture vetoes reclaim for the rest of the function (fail closed).
    out = _run_program("""
        function main {
            main:
                %slot = alloca 32
                %e = getfmp
                mstore %slot, %e
                %p = dalloca 32
                mstore %p, 5
                %v = mload %p
                %q = dalloca 32
                mstore 0, %q
                mstore 32, %v
                return 0, 64
        }
        """)
    assert _word(out, 0) == 64  # %p not reclaimed (static frame is 32 bytes)
    assert _word(out, 1) == 5


# the verified inlined-dret pack-anchor shape: the caller's dead %h is
# reclaim bait at the first dalloca of the inlined body, *after* the cloned
# `getfmp` captured the pack anchor. An engine without the capture veto
# restores the FMP under the anchor, re-allocates %s1/%s2 beneath the pack
# destinations, and the first pack copy clobbers %s2 before the second copy
# reads it (w2 == 11 instead of 22).
_PACK_ANCHOR_SRC = """
function main {
    main:
        %h = dalloca 32
        mstore %h, 5
        %hv = mload %h
        %p1, %p2 = invoke @callee
        %t = dalloca 32
        mstore %t, 77
        %w1 = mload %p1
        %w2 = mload %p2
        %tv = mload %t
        mstore 0, %w1
        mstore 32, %w2
        mstore 64, %hv
        mstore 96, %tv
        return 0, 128
}

function callee {
    callee:
        %retpc = param
        %s1 = dalloca 32
        %s2 = dalloca 32
        mstore %s1, 11
        mstore %s2, 22
        dret 2, %s1, 32, %s2, 32, %retpc
}
"""


def test_inlined_dret_pack_anchor_reclaim_bait():
    out_inlined, _ = _run_program_full_pipeline(_PACK_ANCHOR_SRC, disable_inlining=False)
    out_no_inline, _ = _run_program_full_pipeline(_PACK_ANCHOR_SRC, disable_inlining=True)

    assert _word(out_inlined, 0) == 11
    assert _word(out_inlined, 1) == 22
    assert _word(out_inlined, 2) == 5
    assert _word(out_inlined, 3) == 77
    assert out_inlined == out_no_inline


@pytest.mark.parametrize(("calldata", "expected_q", "expected_vx"), [(b"x", 64, 9), (b"", 32, 7)])
def test_meet_over_three_predecessors_drops_divergent_mark(calldata, expected_q, expected_vx):
    # three predecessors: one carries a live divergent allocation on top of
    # %m, the other two only %m. The top segments disagree, so the meet
    # drops everything: %m is intentionally NOT reclaimed at the join (a
    # restore to it would free the live %x above it), and %q allocates
    # above the leak.
    out = _run_program(
        """
        function main {
            main:
                %m = dalloca 32
                mstore %m, 7
                %ptr = 0
                %c1 = calldatasize
                jnz %c1, @a, @rest

            a:
                %x = dalloca 32
                mstore %x, 9
                %ptr = %x
                jmp @join

            rest:
                %c2 = calldataload 0
                jnz %c2, @b1, @b2

            b1:
                jmp @join

            b2:
                jmp @join

            join:
                %vm = mload %m
                %q = dalloca 32
                mstore %q, 123
                %vx = mload %ptr
                mstore 0, %q
                mstore 32, %vm
                mstore 64, %vx
                return 0, 96
        }
        """,
        calldata,
    )
    assert _word(out, 0) == expected_q
    assert _word(out, 1) == 7
    assert _word(out, 2) == expected_vx


def test_unreachable_block_lowering_is_robust():
    # an unreachable block is still lowered -- no raw opcode may survive
    # check_post_lowering -- but never gets synthesized restores: the
    # dataflow fixpoint only covers reachable blocks, and the dominator
    # tree does not cover unreachable code. (An unreachable *predecessor*
    # of a reachable block crashes MakeSSA's dominator computation long
    # before this pass runs, so that shape is unreachable here.)
    ctx = parse_venom("""
        function main {
            main:
                %p = dalloca 32
                mstore %p, 3
                %v = mload %p
                %q = dalloca 32
                mstore 0, %q
                mstore 32, %v
                return 0, 64

            dead:
                %d = dalloca 32
                mstore %d, 1
                %d2 = dalloca 32
                mstore %d2, 2
                stop
        }
        """)
    fn = ctx.get_function(IRLabel("main"))
    ConcretizeMemLocPass(IRAnalysesCache(fn), fn).run_pass()
    run_ssa(fn)
    FmpLoweringPass(IRAnalysesCache(fn), fn).run_pass()

    opcodes = [inst.opcode for bb in fn.get_basic_blocks() for inst in bb.instructions]
    assert "dalloca" not in opcodes
    assert opcodes.count("bump") == 4

    # the reachable path still reclaims: %p is dead at %q's allocation
    main_insts = fn.get_basic_block("main").instructions
    p_bump = next(inst for inst in main_insts if inst.opcode == "bump")
    restores = [
        inst
        for inst in main_insts
        if inst.opcode == "assign" and inst.operands == [p_bump.get_outputs()[0]]
    ]
    assert len(restores) == 1

    # %d is dead at %d2's allocation, but no restore is synthesized in the
    # unreachable block
    dead_opcodes = [inst.opcode for inst in fn.get_basic_block("dead").instructions]
    assert "assign" not in dead_opcodes


def test_restore_dominance_assertion_fires_on_illegal_restore():
    # hand-construct an illegal reclaim state: a mark defined in one branch
    # arm tracked at a join the definition does not dominate. The emitted
    # restore would be SSA-illegal; the engine's dominance assertion fires.
    ctx = parse_venom("""
        function main {
            main:
                %c = calldatasize
                jnz %c, @a, @b

            a:
                %p = dalloca 32
                mstore %p, 1
                jmp @join

            b:
                jmp @join

            join:
                %q = dalloca 32
                mstore 0, %q
                return 0, 32
        }
        """)
    fn = ctx.get_function(IRLabel("main"))
    ac = IRAnalysesCache(fn)
    lowering = FmpLoweringPass(ac, fn)
    lowering.dynamic_memory = ac.force_analysis(DynamicMemoryAnalysis)
    lowering.fmp_var = fn.get_next_variable()
    lowering.liveness = ac.request_analysis(LivenessAnalysis)
    lowering.base_ptrs = ac.request_analysis(BasePtrAnalysis)
    lowering.dom = ac.request_analysis(DominatorTreeAnalysis)
    lowering._pinned_allocations = frozenset()
    lowering._capture_derived = {}
    lowering._pinned_captures = frozenset()

    p_var = IRVariable("%p")
    lowering._mark_def_bbs = {p_var: fn.get_basic_block("a")}
    state = fmp_lowering._ReclaimState(stack=[p_var])

    q_inst = fn.get_basic_block("join").instructions[0]
    assert q_inst.opcode == "dalloca"
    with pytest.raises(AssertionError, match="dominate"):
        lowering._step(state, q_inst, [])


def test_full_pipeline_rejects_half_lowered_invoke():
    # mixed raw/lowered IR (a raw caller whose invoke already carries the
    # hidden FMP operand) is rejected by check_venom at pipeline entry, so
    # FmpLoweringPass's assert-and-set panic is unreachable from validated
    # input.
    ctx = parse_venom("""
        function main {
            main:
                %a = dalloca 32
                %junk = mload 0
                invoke @callee
                return 0, 32
        }

        function callee {
            callee:
                %fmp = fmp_param
                %retpc = retpc_param
                %p, %next = bump 32, %fmp
                ret %retpc
        }
        """)
    invoke = find_inst(ctx.get_function(IRLabel("main")), "invoke")
    invoke.operands = [IRLabel("callee"), IRVariable("%junk")]

    flags = VenomOptimizationFlags(level=OptimizationLevel.O2, disable_inlining=True)
    with pytest.raises(ExceptionGroup) as excinfo:
        run_passes_on(ctx, flags, disable_mem_checks=True)
    assert any(isinstance(err, MixedFmpIRError) for err in excinfo.value.exceptions)

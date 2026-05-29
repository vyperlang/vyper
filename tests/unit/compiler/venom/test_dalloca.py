import pytest
from pyrevm import EVM, AccountInfo

from tests.venom_utils import parse_from_basic_block
from vyper.compiler.settings import OptimizationLevel, VenomOptimizationFlags
from vyper.evm.address_space import MEMORY
from vyper.evm.assembler.core import assembly_to_evm
from vyper.exceptions import CompilerPanic
from vyper.venom import run_passes_on
from vyper.venom.analysis import (
    IRAnalysesCache,
    LoadAnalysis,
    MemoryAliasAnalysis,
    MemSSA,
    ReadonlyMemoryArgsGlobalAnalysis,
    VarDefinition,
    VariableRangeAnalysis,
)
from vyper.venom.basicblock import IRLabel, IRLiteral
from vyper.venom.effects import Effects
from vyper.venom.parser import parse_venom
from vyper.venom.passes import (
    ConcretizeMemLocPass,
    DallocaLoweringPass,
    MakeSSA,
    PhiEliminationPass,
)
from vyper.venom.passes.dead_store_elimination import DeadStoreElimination
from vyper.venom.passes.function_inliner import FunctionInlinerPass
from vyper.venom.venom_to_assembly import VenomCompiler


def _apply_lowering(fn):
    ConcretizeMemLocPass(IRAnalysesCache(fn), fn).run_pass()
    DallocaLoweringPass(IRAnalysesCache(fn), fn).run_pass()
    ac = IRAnalysesCache(fn)
    MakeSSA(ac, fn).run_pass()
    PhiEliminationPass(ac, fn).run_pass()


def _run_program(src: str, calldata: bytes = b"") -> bytes:
    ctx = parse_venom(src)
    for fn in reversed(list(ctx.functions.values())):
        _apply_lowering(fn)

    asm = VenomCompiler(ctx).generate_evm_assembly()
    bytecode, _ = assembly_to_evm(asm)

    caller = "0x" + "10" * 20
    addr = "0x" + "20" * 20
    evm = EVM()
    evm.set_balance(caller, 1)
    evm.insert_account_info(addr, AccountInfo(code=bytecode))
    return evm.message_call(caller=caller, to=addr, calldata=calldata, gas=1_000_000)


def _run_program_full_pipeline(
    src: str, calldata: bytes = b"", *, disable_inlining: bool
) -> tuple[bytes, object]:
    ctx = parse_venom(src)
    flags = VenomOptimizationFlags(level=OptimizationLevel.O2, disable_inlining=disable_inlining)
    run_passes_on(ctx, flags, disable_mem_checks=True)

    asm = VenomCompiler(ctx).generate_evm_assembly()
    bytecode, _ = assembly_to_evm(asm)

    caller = "0x" + "10" * 20
    addr = "0x" + "20" * 20
    evm = EVM()
    evm.set_balance(caller, 1)
    evm.insert_account_info(addr, AccountInfo(code=bytecode))
    out = evm.message_call(caller=caller, to=addr, calldata=calldata, gas=1_000_000)
    return out, ctx


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
    DallocaLoweringPass(IRAnalysesCache(fn), fn).run_pass()

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
    DallocaLoweringPass(IRAnalysesCache(fn), fn).run_pass()

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
    ac = IRAnalysesCache(fn)

    ac.request_analysis(LoadAnalysis)
    ac.request_analysis(MemSSA)
    ac.request_analysis(MemoryAliasAnalysis)
    ac.request_analysis(VarDefinition)
    ac.request_analysis(VariableRangeAnalysis)
    ac.request_analysis(ReadonlyMemoryArgsGlobalAnalysis)

    DallocaLoweringPass(ac, fn).run_pass()

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


def test_dret_lowering_with_ordinary_return_and_dynamic_buffer():
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


def test_dret_lowering_with_multiple_dynamic_buffers():
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
    import vyper.venom.passes.dalloca_lowering as dalloca_lowering

    monkeypatch.setattr(dalloca_lowering, "version_check", lambda **kwargs: False)
    ctx = parse_venom("""
        function callee {
            callee:
                %retpc = param
                %p = dalloca 32
                dret 1, %p, 32, %retpc
        }
        """)
    fn = ctx.get_function(IRLabel("callee"))
    DallocaLoweringPass(IRAnalysesCache(fn), fn).run_pass()

    opcodes = [inst.opcode for bb in fn.get_basic_blocks() for inst in bb.instructions]
    assert "mcopy" not in opcodes
    assert "staticcall" in opcodes
    assert "assert" in opcodes


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


def test_dret_must_be_lowered_before_inlining():
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
    with pytest.raises(CompilerPanic, match="DallocaLoweringPass must run before"):
        FunctionInlinerPass(analyses, ctx, VenomOptimizationFlags()).run_pass()

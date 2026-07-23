import pytest

from vyper.codegen_venom.buffer import Ptr
from vyper.codegen_venom.context import VenomCodegenContext
from vyper.codegen_venom.value import VyperValue
from vyper.exceptions import CompilerPanic
from vyper.semantics.data_locations import DataLocation
from vyper.semantics.types import BytesT
from vyper.semantics.types.shortcuts import UINT256_T
from vyper.venom.basicblock import IRLiteral
from vyper.venom.builder import VenomBuilder
from vyper.venom.context import IRContext


def _new_context():
    ir_ctx = IRContext()
    fn = ir_ctx.create_function("test_prepare")
    builder = VenomBuilder(ir_ctx, fn)
    ctx = VenomCodegenContext(module_ctx=None, builder=builder)
    return ctx, fn


def _opcodes(fn):
    return [inst.opcode for bb in fn.get_basic_blocks() for inst in bb.instructions]


def test_prepare_storage_word_is_eager_and_emission_free():
    ctx, fn = _new_context()
    src = VyperValue.from_ptr(Ptr(IRLiteral(0), DataLocation.STORAGE), UINT256_T)

    prepared = ctx.prepare_value(src)
    before_access = list(_opcodes(fn))

    assert prepared.is_word
    assert prepared.operand == prepared.word()
    assert _opcodes(fn) == before_access == ["sload"]


def test_prepare_storage_composite_copies_directly_to_one_buffer():
    ctx, fn = _new_context()
    typ = BytesT(64)
    src = VyperValue.from_ptr(Ptr(IRLiteral(0), DataLocation.STORAGE), typ)

    prepared = ctx.prepare_value(src)
    opcodes = _opcodes(fn)

    assert not prepared.is_word
    assert prepared.ptr().location is DataLocation.MEMORY
    assert opcodes.count("alloca") == 1
    assert opcodes.count("mcopy") == 0
    assert opcodes.count("sload") == 1


def test_materialize_transient_composite_uses_one_buffer():
    ctx, fn = _new_context()
    typ = BytesT(64)
    src = VyperValue.from_ptr(Ptr(IRLiteral(0), DataLocation.TRANSIENT), typ)

    materialized = ctx.materialize_value(src)
    opcodes = _opcodes(fn)

    assert materialized.location is DataLocation.MEMORY
    assert opcodes.count("alloca") == 1
    assert opcodes.count("mcopy") == 0
    assert opcodes.count("tload") == 1


def test_prepare_memory_reuses_pointer_and_provenance():
    ctx, fn = _new_context()
    src = ctx.new_temporary_value(BytesT(64), annotation="source")
    before_prepare = list(_opcodes(fn))

    prepared = ctx.prepare_value(src)

    assert prepared.ptr() == src.ptr()
    assert prepared.ptr().buf is src.ptr().buf
    assert _opcodes(fn) == before_prepare


def test_prepare_memory_snapshot_copies_once():
    ctx, fn = _new_context()
    src = ctx.new_temporary_value(BytesT(64), annotation="source")

    prepared = ctx.prepare_value(src, snapshot_memory=True, annotation="snapshot")
    opcodes = _opcodes(fn)

    assert prepared.ptr().buf is not src.ptr().buf
    assert opcodes.count("alloca") == 2
    assert opcodes.count("mcopy") == 1


@pytest.mark.parametrize("location", [DataLocation.CALLDATA, DataLocation.CODE])
def test_prepare_composite_rejects_abi_layout_sources(location):
    ctx, _ = _new_context()
    src = VyperValue.from_ptr(Ptr(IRLiteral(0), location), BytesT(64))

    with pytest.raises(CompilerPanic, match="cannot flat-copy ABI-layout value"):
        ctx.prepare_value(src)


def test_prepared_value_rejects_the_wrong_representation_accessor():
    ctx, _ = _new_context()
    word = ctx.prepare_value(
        VyperValue.from_ptr(Ptr(IRLiteral(0), DataLocation.STORAGE), UINT256_T)
    )
    memory = ctx.prepare_value(ctx.new_temporary_value(BytesT(64)))

    with pytest.raises(CompilerPanic, match="cannot get ptr from prepared word value"):
        word.ptr()
    with pytest.raises(CompilerPanic, match="cannot get word from prepared memory value"):
        memory.word()

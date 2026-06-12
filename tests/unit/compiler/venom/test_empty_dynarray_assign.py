import pytest

from vyper.codegen_venom.module import generate_runtime_venom
from vyper.compiler.phases import CompilerData
from vyper.compiler.settings import Settings, anchor_settings


def _lower(code):
    # raw lowering, before any optimization passes run
    data = CompilerData(code, settings=Settings(experimental_codegen=True))
    with anchor_settings(data.settings):
        return generate_runtime_venom(data.global_ctx, data.settings)


def _instructions(ctx):
    return [
        inst
        for fn in ctx.functions.values()
        for bb in fn.get_basic_blocks()
        for inst in bb.instructions
    ]


@pytest.mark.parametrize(
    "decl,store_opcode",
    [("a: DynArray[uint256, 10]", "sstore"), ("a: transient(DynArray[uint256, 10])", "tstore")],
)
def test_empty_dynarray_assign_is_single_length_store(decl, store_opcode):
    code = f"""
{decl}

@external
def clear():
    self.a = []
    """
    ctx = _lower(code)

    opcodes = [inst.opcode for inst in _instructions(ctx)]
    # fast path: a single store of the (zero) length word, no copy loop
    assert opcodes.count(store_opcode) == 1

    labels = [str(bb.label) for fn in ctx.functions.values() for bb in fn.get_basic_blocks()]
    assert not any("dyn_cond" in label for label in labels)


def test_empty_dynarray_assign_memory_no_copy():
    code = """
@external
def clear() -> uint256:
    a: DynArray[uint256, 10] = []
    a = []
    return len(a)
    """
    ctx = _lower(code)

    opcodes = [inst.opcode for inst in _instructions(ctx)]
    # fast path: zero the length word directly, no staging buffer copies
    assert "mcopy" not in opcodes

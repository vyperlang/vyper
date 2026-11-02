import pytest

from vyper.codegen_venom.module import generate_venom_runtime
from vyper.compiler.phases import CompilerData
from vyper.compiler.settings import OptimizationLevel, Settings, anchor_settings
from vyper.venom.basicblock import IRLiteral

ABI_DECODE = """
@external
def f(x: Bytes[288]) -> Bytes[200]:
    return abi_decode(x, Bytes[200])
"""

RETURNDATA_DECODE = """
interface I:
    def g() -> Bytes[100]: view

@external
def f(a: address) -> Bytes[100]:
    return staticcall I(a).g()
"""


def _runtime_venom(code: str):
    # the IR straight out of codegen, before any pass
    settings = Settings(experimental_codegen=True, optimize=OptimizationLevel.NONE)
    compiler_data = CompilerData(code, settings=settings)
    with anchor_settings(compiler_data.settings):
        return generate_venom_runtime(compiler_data.global_ctx, compiler_data.settings)


@pytest.mark.parametrize("code", [ABI_DECODE, RETURNDATA_DECODE], ids=["abi_decode", "returndata"])
def test_bytestring_decode_from_memory_copies_payload_size(code):
    # the payload can sit at any offset that the bounds checks accept, e.g.
    # near the end of its buffer, so a copy of the type's maximum size can
    # read past the buffer; the copies here are all bytestring payloads
    ctx = _runtime_venom(code)
    for fn in ctx.functions.values():
        for bb in fn.get_basic_blocks():
            for inst in bb.instructions:
                if inst.opcode == "mcopy":
                    size = inst.operands[0]  # operands are reversed: dst, src, size
                    assert not isinstance(size, IRLiteral), inst

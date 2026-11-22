import pytest

from vyper.codegen_venom.module import generate_venom_runtime
from vyper.compiler.phases import CompilerData
from vyper.compiler.settings import OptimizationLevel, Settings, anchor_settings
from vyper.exceptions import TypeMismatch

CODE = """
struct S:
    x: uint256
    y: uint256

@external
def foo(a: {typ}, b: {typ}) -> bool:
    return a {op} b
"""


# GH issue 4960: venom codegen lowered these to an `eq` of the two memory
# pointers, so the result did not depend on the values
@pytest.mark.parametrize("op", ["==", "!="])
@pytest.mark.parametrize("typ", ["uint256[3]", "DynArray[uint256, 4]", "S"])
def test_compare_complex_types_blocked(op, typ):
    settings = Settings(experimental_codegen=True, optimize=OptimizationLevel.NONE)
    compiler_data = CompilerData(CODE.format(typ=typ, op=op), settings=settings)
    with anchor_settings(compiler_data.settings):
        with pytest.raises(TypeMismatch) as e:
            generate_venom_runtime(compiler_data.global_ctx, compiler_data.settings)
    assert e.value.message == f"operation not yet supported for {typ}, {typ}, see issue #2638"

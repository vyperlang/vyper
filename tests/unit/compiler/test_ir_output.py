import pytest

from vyper.compiler import compile_code
from vyper.compiler.settings import Settings
from vyper.venom.context import IRContext


@pytest.mark.parametrize("output_format", ["ir_dict", "ir_runtime_dict"])
@pytest.mark.parametrize(
    "code",
    [
        "@external\ndef foo() -> uint256:\n    return 1\n",
        "@external\ndef foo(x: Bytes[INF]) -> Bytes[INF]:\n    return x\n",
    ],
)
def test_venom_rejects_legacy_ir_dictionary_formats(output_format, code):
    with pytest.raises(ValueError, match=f"{output_format} is not supported"):
        compile_code(
            code, output_formats=[output_format], settings=Settings(experimental_codegen=True)
        )


@pytest.mark.parametrize("output_format", ["ir_dict", "ir_runtime_dict"])
def test_legacy_ir_dictionary_formats(output_format):
    code = "@external\ndef foo() -> uint256:\n    return 1\n"
    result = compile_code(
        code, output_formats=[output_format], settings=Settings(experimental_codegen=False)
    )
    assert isinstance(result[output_format], dict)
    assert result[output_format]


@pytest.mark.parametrize("output_format", ["ir", "ir_runtime"])
def test_venom_ir_formats_support_unbounded_types(output_format):
    code = "@external\ndef foo(x: Bytes[INF]) -> Bytes[INF]:\n    return x\n"
    result = compile_code(
        code, output_formats=[output_format], settings=Settings(experimental_codegen=True)
    )
    assert isinstance(result[output_format], IRContext)

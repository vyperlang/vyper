import pytest

from vyper import compile_code
from vyper.compiler.settings import Settings
from vyper.exceptions import CompilerPanic

DATA_VIEW_USES = {
    "keccak256": "x: bytes32 = keccak256(__VIEW__)",
    "sha256": "x: bytes32 = sha256(__VIEW__)",
    "extract32": "x: bytes32 = extract32(__VIEW__, 0)",
    "raw_revert": "raw_revert(__VIEW__)",
    "abi_decode": "x: uint256 = abi_decode(__VIEW__, uint256)",
    "create_from_blueprint": "x: address = create_from_blueprint("
    "a, __VIEW__, raw_args=True, revert_on_failure=False)",
}


@pytest.mark.parametrize(
    "view, error",
    [
        ("msg.data", r"msg\.data requires Slice/Len context"),
        ("self.code", r"\.code requires slice\(\) context"),
        ("a.code", r"\.code requires slice\(\) context"),
    ],
    ids=["msg.data", "self.code", "address.code"],
)
@pytest.mark.parametrize("use", DATA_VIEW_USES.values(), ids=DATA_VIEW_USES.keys())
def test_undeclared_data_views_fail_precisely(view, error, use):
    source = f"""
@external
def foo(a: address):
    {use.replace("__VIEW__", view)}
"""

    # Only len(), slice(), and raw_call() declare data-view policies. Other
    # consumers must reach Expr's precise diagnostic instead of receiving a
    # missing prepared argument or treating an extcode address as a Bytes ptr.
    with pytest.raises(CompilerPanic, match=error):
        compile_code(
            source, output_formats=["bytecode"], settings=Settings(experimental_codegen=True)
        )


def _runtime_opcodes(source):
    output = compile_code(
        source, output_formats=["opcodes_runtime"], settings=Settings(experimental_codegen=True)
    )
    return output["opcodes_runtime"].split()


def _runtime_ir_lines(source):
    output = compile_code(
        source, output_formats=["ir_runtime"], settings=Settings(experimental_codegen=True)
    )
    return str(output["ir_runtime"]).splitlines()


def _assert_ir_operation_before(lines, earlier, later):
    earlier = earlier.lower()
    later = later.lower()
    earlier_indices = [i for i, line in enumerate(lines) if f" = {earlier}" in line]
    later_indices = [i for i, line in enumerate(lines) if f" = {later}" in line]

    assert earlier_indices, f"missing {earlier}"
    assert later_indices, f"missing {later}"
    message = f"expected every {earlier} before {later}; got {earlier_indices=}, {later_indices=}"
    assert max(earlier_indices) < min(later_indices), message


@pytest.mark.parametrize(
    "declaration, load_opcode",
    [("amount: uint256", "SLOAD"), ("amount: transient(uint256)", "TLOAD")],
)
def test_positional_primitive_is_loaded_before_explicit_gas_kwarg(declaration, load_opcode):
    source = f"""
{declaration}

@external
def foo(to: address):
    send(to, self.amount, gas=msg.gas)
"""

    _assert_ir_operation_before(_runtime_ir_lines(source), load_opcode, "GAS")


@pytest.mark.parametrize(
    "declaration, load_opcode",
    [("payload: Bytes[32]", "SLOAD"), ("payload: transient(Bytes[32])", "TLOAD")],
)
def test_positional_bytes_are_loaded_before_default_gas(declaration, load_opcode):
    source = f"""
{declaration}

@external
def foo(to: address):
    raw_call(to, self.payload)
"""

    _assert_ir_operation_before(_runtime_ir_lines(source), load_opcode, "GAS")


@pytest.mark.parametrize(
    "declaration, load_opcode",
    [("initcode: Bytes[32]", "SLOAD"), ("initcode: transient(Bytes[32])", "TLOAD")],
)
def test_positional_initcode_is_loaded_before_gas_sensitive_value(declaration, load_opcode):
    source = f"""
{declaration}

@external
def foo() -> address:
    return raw_create(self.initcode, value=msg.gas, revert_on_failure=False)
"""

    _assert_ir_operation_before(_runtime_ir_lines(source), load_opcode, "GAS")


@pytest.mark.parametrize(
    "salt, create_opcode", [("", "CREATE"), (", salt=0x" + "00" * 32, "CREATE2")]
)
def test_absent_salt_and_explicit_zero_select_different_create_opcodes(salt, create_opcode):
    source = f"""
@external
def foo() -> address:
    return raw_create(b"x"{salt}, revert_on_failure=False)
"""

    opcodes = _runtime_opcodes(source)
    other_opcode = "CREATE2" if create_opcode == "CREATE" else "CREATE"
    assert create_opcode in opcodes
    assert other_opcode not in opcodes

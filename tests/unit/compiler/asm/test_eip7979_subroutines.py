"""
EIP-7979 subroutines (``--evm-version future``): internal calls compile to
CALLSUB / CALLDEST / RETURNSUB instead of pushed return labels and jumps.

These are compile-only tests: the test EVMs do not implement the
instructions, so execution is checked elsewhere.
"""

from vyper.compiler import compile_code
from vyper.compiler.phases import CompilerData
from vyper.compiler.settings import Settings
from vyper.evm.assembler.instructions import PUSHLABEL, Label, SubroutineLabel
from vyper.evm.assembler.optimizer import _merge_jumpdests
from vyper.evm.opcodes import EVM_VERSIONS, _evm_opcodes

CODE = """
@internal
@pure
def square(x: uint256) -> uint256:
    return x * x

@internal
@pure
def sum_of_squares(a: uint256, b: uint256) -> uint256:
    return self.square(a) + self.square(b)

@external
@pure
def compute(a: uint256, b: uint256) -> uint256:
    return self.sum_of_squares(a, b)
"""


def _runtime_asm(evm_version):
    data = CompilerData(CODE, settings=Settings(evm_version=evm_version))
    return data.assembly_runtime


def _opcode_names(asm):
    return [x for x in asm if isinstance(x, str)]


def test_future_has_subroutine_opcodes():
    ops = _evm_opcodes[EVM_VERSIONS["future"]]
    assert ops["CALLSUB"][0] == 0xB0
    assert ops["CALLDEST"][0] == 0xB1
    assert ops["RETURNSUB"][0] == 0xB2
    assert "CALLSUB" not in _evm_opcodes[EVM_VERSIONS["prague"]]


def test_internal_calls_use_subroutines():
    asm = _runtime_asm("future")
    names = _opcode_names(asm)
    # three call sites (square twice, sum_of_squares once), two returns
    assert names.count("CALLSUB") == 3
    assert names.count("RETURNSUB") == 2
    # every function entry is a subroutine label
    assert sum(isinstance(x, SubroutineLabel) for x in asm) >= 2
    # the only remaining jumps are conditional: no return-label JUMPs
    assert "JUMP" not in names
    assert "JUMPI" in names


def test_default_version_unchanged():
    asm = _runtime_asm("prague")
    names = _opcode_names(asm)
    assert "CALLSUB" not in names
    assert "RETURNSUB" not in names
    assert not any(isinstance(x, SubroutineLabel) for x in asm)
    assert "JUMP" in names


def test_bytecode_contains_instructions():
    out = compile_code(
        CODE, output_formats=["bytecode_runtime"], settings=Settings(evm_version="future")
    )
    code = bytes.fromhex(out["bytecode_runtime"].removeprefix("0x"))
    # a CALLSUB is always immediately preceded by a PUSH2 label
    assert any(code[i] == 0x61 and code[i + 3] == 0xB0 for i in range(len(code) - 3))
    assert 0xB2 in code


def test_merge_jumpdests_keeps_subroutine_entries():
    # LABEL x LABEL y: references to x move to y, and since x was a
    # subroutine entry, y becomes one.
    x, y = SubroutineLabel("x"), Label("y")
    asm = [PUSHLABEL(x), "CALLSUB", "STOP", x, y, "RETURNSUB"]
    assert _merge_jumpdests(asm)
    assert asm[0] == PUSHLABEL(y)
    assert any(isinstance(i, SubroutineLabel) and i.label == "y" for i in asm)


def test_no_jump_threading_through_subroutine_entry():
    # LABEL x PUSHLABEL y JUMP with x a subroutine entry: not threaded, so
    # a CALLSUB x is never redirected onto a plain label.
    x, y = SubroutineLabel("x"), Label("y")
    asm = [PUSHLABEL(x), "CALLSUB", "STOP", x, PUSHLABEL(y), "JUMP", y, "RETURNSUB"]
    _merge_jumpdests(asm)
    assert asm[0] == PUSHLABEL(x)


def test_linear_selector_section_is_static():
    # Two external functions: the default is a selector table with a computed
    # jump; the linear section has only pushed destinations. Under `future`
    # the linear section makes the whole runtime static control flow.
    code = """
@external
@pure
def f(a: uint256) -> uint256:
    return a + 1

@external
@pure
def g(a: uint256) -> uint256:
    return a * 2
"""
    default = CompilerData(code, settings=Settings(evm_version="future")).assembly_runtime
    linear = CompilerData(
        code, settings=Settings(evm_version="future", linear_selector_section=True)
    ).assembly_runtime
    default_names = _opcode_names(default)
    linear_names = _opcode_names(linear)
    # the table dispatch jumps through a value loaded from memory
    assert "JUMP" in default_names
    # the linear dispatch is JUMPIs to pushed labels only
    assert "JUMP" not in linear_names
    assert "JUMPI" in linear_names

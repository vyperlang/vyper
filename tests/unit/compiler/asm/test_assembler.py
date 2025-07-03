import pytest

from vyper.evm.assembler.core import (
    PUSH_OFST,
    _assembly_to_evm,
    _resolve_constants,
    assembly_to_evm,
    resolve_symbols,
)
from vyper.evm.assembler.symbols import CONST, CONST_ADD, CONST_MAX, CONST_SUB, CONSTREF, Label
from vyper.exceptions import CompilerPanic


def test_const_add():
    asm = [CONST("a", 1), CONST("b", 2), CONST_ADD("c", "a", "b"), CONST_ADD("d", "c", 10)]
    symbol_map = {}
    label_dependent_consts = _resolve_constants(asm, symbol_map)
    assert len(label_dependent_consts) == 0
    assert symbol_map[CONSTREF("c")] == 3
    assert symbol_map[CONSTREF("d")] == 13


def test_const_sub():
    asm = [CONST("a", 1), CONST("b", 2), CONST_SUB("c", "a", "b"), CONST_ADD("d", "c", 10)]
    symbol_map = {}
    label_dependent_consts = _resolve_constants(asm, symbol_map)

    assert len(label_dependent_consts) == 0
    assert symbol_map[CONSTREF("c")] == -1
    assert symbol_map[CONSTREF("d")] == 9


def test_const_max():
    asm = [CONST("a", 1), CONST("b", 2), CONST_MAX("c", "a", "b"), CONST_MAX("d", "c", 10)]
    symbol_map = {}
    label_dependent_consts = _resolve_constants(asm, symbol_map)
    assert len(label_dependent_consts) == 0
    assert symbol_map[CONSTREF("c")] == 2
    assert symbol_map[CONSTREF("d")] == 10


def test_const_add_with_label():
    asm = [
        CONST("a", 5),
        Label("my_label"),
        "JUMPDEST",  # This will create actual bytecode at my_label
        CONST_ADD("b", "a", "my_label"),  # a + my_label position
        CONST_ADD("c", "my_label", 100),  # my_label position + 100
        PUSH_OFST(CONSTREF("b"), 0),  # Push the computed constant value
        PUSH_OFST(CONSTREF("c"), 0),  # Push the computed constant value
    ]

    # Resolve symbols and constants
    symbol_map, _ = resolve_symbols(asm)

    # Check that constants were calculated correctly
    assert symbol_map[CONSTREF("a")] == 5
    assert symbol_map[Label("my_label")] == 0  # First position after constants
    assert symbol_map[CONSTREF("b")] == 5  # a + my_label = 5 + 0
    assert symbol_map[CONSTREF("c")] == 100  # my_label + 100 = 0 + 100

    # Compile to bytecode
    bytecode, _ = assembly_to_evm(asm)
    assert len(bytecode) > 0



def test_const_add_with_label_overflow():
    # Create assembly with a large offset that will overflow when added to a label
    asm = [
        Label("start"),
        "JUMPDEST",
        CONST("huge_offset", 65000),
        CONST_ADD("overflow", "start", 1000),  # This is OK (0 + 1000)
        CONST_ADD("will_overflow", "overflow", "huge_offset"),  # 1000 + 65000 = 66000 > 65535
        PUSH_OFST(CONSTREF("will_overflow"), 0),
    ]

    with pytest.raises(CompilerPanic) as exc_info:
        resolve_symbols(asm)

    assert "exceeds 16-bit limit" in str(exc_info.value)
    assert "will_overflow" in str(exc_info.value)


def test_push_ofst_with_label_dependent_const_overflow():
    # Test PUSH_OFST overflow checking during bytecode generation

    # Manually create a symbol map that would cause overflow
    symbol_map = {Label("far_label"): 10000, CONSTREF("near_limit"): 65000}  # Just under the limit

    # This should fail when PUSH_OFST tries to add an offset that causes overflow
    test_asm = [PUSH_OFST(CONSTREF("near_limit"), 1000)]  # 65000 + 1000 > 65535

    label_dependent_consts = {"near_limit"}  # Mark as label-dependent

    with pytest.raises(CompilerPanic) as exc_info:
        _assembly_to_evm(test_asm, symbol_map, label_dependent_consts)

    assert "exceeds 16-bit limit" in str(exc_info.value)

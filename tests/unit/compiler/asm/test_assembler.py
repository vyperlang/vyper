from vyper.evm.assembler import CONST, CONST_ADD, CONST_MAX, CONSTREF, _resolve_constants


def test_const_add():
    asm = [CONST("a", 1), CONST("b", 2), CONST_ADD("c", "a", "b"), CONST_ADD("d", "c", 10)]
    symbol_map = {}
    _resolve_constants(asm, symbol_map)
    assert symbol_map[CONSTREF("c")] == 3
    assert symbol_map[CONSTREF("d")] == 13


def test_const_max():
    asm = [CONST("a", 1), CONST("b", 2), CONST_MAX("c", "a", "b"), CONST_MAX("d", "c", 10)]
    symbol_map = {}
    _resolve_constants(asm, symbol_map)
    assert symbol_map[CONSTREF("c")] == 2
    assert symbol_map[CONSTREF("d")] == 10

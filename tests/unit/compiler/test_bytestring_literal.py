import pytest

from vyper.codegen_venom.bytestring_literal import (
    chain_bytes,
    codecopy_bytes,
    push_cost,
    should_codecopy,
)
from vyper.codegen_venom.module import generate_runtime_venom
from vyper.compiler.phases import CompilerData
from vyper.compiler.settings import OptimizationLevel, Settings, anchor_settings
from vyper.venom.basicblock import IRLiteral
from vyper.venom.effects import Effects

# every word of this is dense: no NOT or SHL shortcut applies
DENSE = bytes(range(1, 256)) * 2

ALPHABET = "abcdefghijklmnopqrstuvwxyz" * 8


def test_push_cost_reduced():
    assert push_cost(0, reduced=True) == 1  # PUSH0
    assert push_cost(1, reduced=True) == 2  # PUSH1
    assert push_cost(int.from_bytes(DENSE[:32], "big"), reduced=True) == 33  # PUSH32
    assert push_cost(2**256 - 1, reduced=True) == 2  # PUSH0, NOT
    assert push_cost(2**256 - 0x100, reduced=True) == 3  # PUSH1 0xff, NOT
    assert push_cost(1 << 255, reduced=True) == 5  # PUSH1 1, PUSH1 255, SHL
    assert push_cost(0x73747576 << 224, reduced=True) == 8  # PUSH4, PUSH1, SHL


def test_push_cost_plain():
    # without ReduceLiteralsCodesize every non-zero word is a plain PUSHn
    assert push_cost(0, reduced=False) == 1
    assert push_cost(2**256 - 1, reduced=False) == 33
    assert push_cost(1 << 255, reduced=False) == 33
    assert push_cost(0x73747576 << 224, reduced=False) == 33


def test_chain_bytes():
    # PUSH32, PUSH1 addr, MSTORE per dense word
    assert chain_bytes(DENSE[:64], reduced=True) == 2 * 36
    assert chain_bytes(DENSE[:64], reduced=False) == 2 * 36
    # the padded tail word is cheap only with SHL: PUSH1, PUSH1, SHL, PUSH1 addr, MSTORE
    assert chain_bytes(DENSE[:33], reduced=True) == 36 + 8
    assert chain_bytes(DENSE[:33], reduced=False) == 36 + 36
    # zero words: PUSH0, PUSH1 addr, MSTORE
    assert chain_bytes(b"\x00" * 96, reduced=False) == 3 * 4


def test_codecopy_bytes():
    assert codecopy_bytes(96, padded=True) == 96 + 9
    assert codecopy_bytes(100, padded=True) == 128 + 9
    assert codecopy_bytes(96, padded=False) == 96 + 9
    assert codecopy_bytes(100, padded=False) == 100 + 9 + 4  # plus the tail zeroing store


# codesize levels: exact item plus tail store, chain priced with NOT/SHL forms
@pytest.mark.parametrize(
    "n,expected",
    [
        (32, False),  # single word, never
        (33, False),  # 46 vs 44
        (63, False),  # 76 vs 72
        (64, False),  # 73 vs 72
        (65, True),  # 78 vs 80
        (96, True),  # 105 vs 108
        (97, True),  # 110 vs 116
        (100, True),  # 113 vs 119
    ],
)
def test_should_codecopy_codesize(n, expected):
    assert should_codecopy(DENSE[:n], padded=False, reduced=True) is expected


# gas levels: padded item, chain priced with plain PUSHn only
@pytest.mark.parametrize(
    "n,expected",
    [
        (32, False),  # single word, never
        (33, False),  # 73 vs 72
        (63, False),  # 73 vs 72
        (64, False),  # 73 vs 72
        (65, True),  # 105 vs 108
        (96, True),  # 105 vs 108
        (97, True),  # 137 vs 144
        (100, True),  # 137 vs 144
    ],
)
def test_should_codecopy_gas(n, expected):
    assert should_codecopy(DENSE[:n], padded=True, reduced=False) is expected


@pytest.mark.parametrize("padded,reduced", [(True, False), (False, True)])
def test_should_codecopy_zero_words(padded, reduced):
    # 3 zero words cost 12 bytes as stores, 105 as a data item
    assert not should_codecopy(b"\x00" * 96, padded, reduced)


def _runtime_venom(code: str, level: OptimizationLevel):
    settings = Settings(experimental_codegen=True, optimize=level)
    compiler_data = CompilerData(code, settings=settings)
    # `_opt_codesize()` reads the global settings, like the compiler driver
    with anchor_settings(compiler_data.settings):
        return generate_runtime_venom(compiler_data.global_ctx, compiler_data.settings)


def _literal_sections(ctx):
    return [s for s in ctx.data_segment if s.label.value.endswith("_literal")]


def _instructions(ctx):
    return [inst for bb in ctx.get_basic_blocks() for inst in bb.instructions]


@pytest.mark.parametrize(
    "level,n,expected_item",
    [
        (OptimizationLevel.GAS, 96, ALPHABET[:96].encode()),
        (OptimizationLevel.GAS, 100, ALPHABET[:100].encode().ljust(128, b"\x00")),
        (OptimizationLevel.CODESIZE, 96, ALPHABET[:96].encode()),
        (OptimizationLevel.CODESIZE, 100, ALPHABET[:100].encode()),
    ],
)
def test_literal_codecopy_ir(level, n, expected_item):
    code = f"""
@external
def foo() -> String[{n}]:
    return "{ALPHABET[:n]}"
    """
    ctx = _runtime_venom(code, level)

    (section,) = _literal_sections(ctx)
    (item,) = section.data_items
    assert item.data == expected_item

    insts = _instructions(ctx)
    (codecopy,) = [inst for inst in insts if inst.opcode == "codecopy"]
    size, label, _ = codecopy.operands
    assert size == IRLiteral(len(expected_item))
    assert label == section.label

    bb = codecopy.parent.instructions
    stores = [inst for inst in bb if inst.opcode == "mstore"]
    # the length store is the last memory write of the sequence: nothing
    # between the copy and it touches memory
    (length_store,) = [inst for inst in stores if inst.operands[0] == IRLiteral(n)]
    copy_idx, length_idx = bb.index(codecopy), bb.index(length_store)
    assert copy_idx < length_idx
    between = bb[copy_idx + 1 : length_idx]
    assert not any(Effects.MEMORY in inst.get_write_effects() for inst in between)

    # the last data word is zeroed before the copy for an exact item that
    # is not word-aligned; a padded item needs no tail store
    tail_stores = [inst for inst in bb[:copy_idx] if inst in stores]
    needs_tail_store = len(expected_item) % 32 != 0
    assert [inst.operands[0] for inst in tail_stores] == (
        [IRLiteral(0)] if needs_tail_store else []
    )


@pytest.mark.parametrize("level", [OptimizationLevel.GAS, OptimizationLevel.CODESIZE])
def test_literal_below_size_threshold_keeps_mstore_chain(level):
    # two words: 73 vs 72 bytes at gas levels, 76 vs 72 at codesize levels
    code = f"""
@external
def foo() -> String[63]:
    return "{ALPHABET[:63]}"
    """
    ctx = _runtime_venom(code, level)
    assert len(_literal_sections(ctx)) == 0
    assert not any(inst.opcode == "codecopy" for inst in _instructions(ctx))


def test_two_literals_two_sections():
    first = ALPHABET[:96]
    second = ALPHABET[1:97]
    code = f"""
@external
def foo() -> String[96]:
    return "{first}"

@external
def bar() -> String[96]:
    return "{second}"
    """
    ctx = _runtime_venom(code, OptimizationLevel.CODESIZE)
    sections = _literal_sections(ctx)
    assert [s.data_items[0].data for s in sections] == [first.encode(), second.encode()]
    first_label, second_label = [s.label for s in sections]
    assert first_label != second_label
    copies = [inst for inst in _instructions(ctx) if inst.opcode == "codecopy"]
    assert [inst.operands[1] for inst in copies] == [first_label, second_label]


def test_literal_in_internal_function_single_section():
    # the function body is lowered once, so its literal gets one data item
    # regardless of how many call sites there are
    code = f"""
@internal
def _msg() -> String[96]:
    return "{ALPHABET[:96]}"

@external
def foo() -> String[96]:
    return self._msg()

@external
def bar() -> String[96]:
    return self._msg()
    """
    ctx = _runtime_venom(code, OptimizationLevel.CODESIZE)
    assert len(_literal_sections(ctx)) == 1

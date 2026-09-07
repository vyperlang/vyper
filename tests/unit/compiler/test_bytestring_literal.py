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
from vyper.venom.basicblock import IRLabel, IRLiteral
from vyper.venom.effects import Effects

# every word of this is dense: no NOT or SHL shortcut applies
DENSE = bytes(range(1, 256)) * 2

ALPHABET = "abcdefghijklmnopqrstuvwxyz" * 8


def test_push_cost():
    assert push_cost(0) == 1  # PUSH0
    assert push_cost(1) == 2  # PUSH1
    assert push_cost(int.from_bytes(DENSE[:32], "big")) == 33  # PUSH32
    assert push_cost(2**256 - 1) == 2  # PUSH0, NOT
    assert push_cost(2**256 - 0x100) == 3  # PUSH1 0xff, NOT
    assert push_cost(1 << 255) == 5  # PUSH1 1, PUSH1 255, SHL
    assert push_cost(0x73747576 << 224) == 8  # PUSH4, PUSH1, SHL


def test_chain_bytes():
    # PUSH32, PUSH1 addr, MSTORE per dense word
    assert chain_bytes(DENSE[:64]) == 2 * 36
    # the padded tail word is cheap: PUSH1, PUSH1, SHL, PUSH1 addr, MSTORE
    assert chain_bytes(DENSE[:33]) == 36 + 8
    # zero words: PUSH0, PUSH1 addr, MSTORE
    assert chain_bytes(b"\x00" * 96) == 3 * 4


def test_codecopy_bytes():
    assert codecopy_bytes(96, padded=True) == 96 + 9
    assert codecopy_bytes(100, padded=True) == 128 + 9
    assert codecopy_bytes(96, padded=False) == 96 + 9
    assert codecopy_bytes(100, padded=False) == 100 + 9 + 4  # plus the tail zeroing store


@pytest.mark.parametrize(
    "n,padded,expected",
    [
        (32, True, False),  # single word, never
        (32, False, False),
        (33, True, False),  # 73 vs 44
        (33, False, False),  # 46 vs 44
        (63, True, False),  # 73 vs 72
        (63, False, False),  # 76 vs 72
        (64, True, False),  # 73 vs 72
        (64, False, False),  # 73 vs 72
        (65, True, False),  # 105 vs 80
        (65, False, True),  # 78 vs 80
        (96, True, True),  # 105 vs 108
        (96, False, True),  # 105 vs 108
    ],
)
def test_should_codecopy(n, padded, expected):
    assert should_codecopy(DENSE[:n], padded) is expected


@pytest.mark.parametrize("padded", [True, False])
def test_should_codecopy_zero_words(padded):
    # 3 zero words cost 12 bytes as stores, 105 as a data item
    assert not should_codecopy(b"\x00" * 96, padded)


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

    # the last data word is zeroed before the copy, unless the data is
    # word-aligned
    tail_stores = [inst for inst in bb[:copy_idx] if inst in stores]
    assert [inst.operands[0] for inst in tail_stores] == ([IRLiteral(0)] if n % 32 else [])


def test_literal_below_gate_keeps_mstore_chain():
    code = f"""
@external
def foo() -> String[100]:
    return "{ALPHABET[:100]}"
    """
    ctx = _runtime_venom(code, OptimizationLevel.GAS)
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
    labels = [s.label for s in sections]
    assert len(set(labels)) == 2
    assert all(isinstance(label, IRLabel) for label in labels)
    copies = [inst for inst in _instructions(ctx) if inst.opcode == "codecopy"]
    assert [inst.operands[1] for inst in copies] == labels


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

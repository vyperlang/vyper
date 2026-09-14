import pytest

from vyper.codegen_venom.bytestring_literal import (
    chain_bytes,
    codecopy_bytes,
    push_cost,
    should_codecopy,
)
from vyper.codegen_venom.module import generate_deploy_venom, generate_runtime_venom
from vyper.compiler.phases import CompilerData
from vyper.compiler.settings import OptimizationLevel, Settings, anchor_settings
from vyper.utils import ceil32
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
    # the item, 2 for its metadata length entry, 9 per copy
    assert codecopy_bytes(96, padded=True, uses=1) == 96 + 2 + 9
    assert codecopy_bytes(100, padded=True, uses=1) == 128 + 2 + 9
    assert codecopy_bytes(96, padded=False, uses=1) == 96 + 2 + 9
    assert codecopy_bytes(100, padded=False, uses=1) == 100 + 2 + 9 + 4  # plus the tail store
    # the item and its entry are shared, the copy (and the tail store) is paid per use
    assert codecopy_bytes(100, padded=True, uses=3) == 128 + 2 + 3 * 9
    assert codecopy_bytes(100, padded=False, uses=3) == 100 + 2 + 3 * (9 + 4)


# codesize levels: exact item plus metadata entry and tail store, chain
# priced with NOT/SHL forms
@pytest.mark.parametrize(
    "n,expected",
    [
        (32, False),  # 43 vs 36
        (33, False),  # 48 vs 44
        (63, False),  # 78 vs 72
        (64, False),  # 75 vs 72
        (65, False),  # 80 vs 80, a tie keeps the chain
        (96, True),  # 107 vs 108
        (97, True),  # 112 vs 116
        (100, True),  # 115 vs 119
    ],
)
def test_should_codecopy_codesize(n, expected):
    assert should_codecopy(DENSE[:n], padded=False, reduced=True, uses=1) is expected


# gas levels: padded item, chain priced with plain PUSHn only
@pytest.mark.parametrize(
    "n,expected",
    [
        (32, False),  # 43 vs 36
        (33, False),  # 75 vs 72
        (63, False),  # 75 vs 72
        (64, False),  # 75 vs 72
        (65, True),  # 107 vs 108
        (96, True),  # 107 vs 108
        (97, True),  # 139 vs 144
        (100, True),  # 139 vs 144
    ],
)
def test_should_codecopy_gas(n, expected):
    assert should_codecopy(DENSE[:n], padded=True, reduced=False, uses=1) is expected


@pytest.mark.parametrize("padded,reduced", [(True, False), (False, True)])
def test_should_codecopy_zero_words(padded, reduced):
    # 3 zero words cost 12 bytes as stores, 107 as a data item
    assert not should_codecopy(b"\x00" * 96, padded, reduced, uses=1)


# one data item against one chain per use; expected for 1, 2 and 3 uses.
# the comments give the copy costs (item plus 2 for its metadata entry
# plus 9 per use, 13 with a tail store) against the chain costs (per use:
# 36 for a dense word, the partial word PUSHn, PUSH1, SHL when reduced)
@pytest.mark.parametrize(
    "n,padded,reduced,expected",
    [
        # one word of 8 bytes: chain 36 plain, 15 reduced
        (8, True, False, (False, True, True)),  # 43, 52, 61 vs 36, 72, 108
        (8, True, True, (False, False, False)),  # 43, 52, 61 vs 15, 30, 45
        (8, False, False, (True, True, True)),  # 23, 36, 49 vs 36, 72, 108
        (8, False, True, (False, False, False)),  # 23, 36, 49 vs 15, 30, 45
        # one word of 15 bytes: chain 36 plain, 22 reduced
        (15, True, False, (False, True, True)),  # 43, 52, 61 vs 36, 72, 108
        (15, True, True, (False, False, True)),  # 43, 52, 61 vs 22, 44, 66
        (15, False, False, (True, True, True)),  # 30, 43, 56 vs 36, 72, 108
        (15, False, True, (False, True, True)),  # 30, 43, 56 vs 22, 44, 66
        # one word of 20 and 22 bytes: against a PUSH32 chain the exact
        # single-use item pays for itself up to 20 bytes
        (20, False, False, (True, True, True)),  # 35, 48, 61 vs 36, 72, 108
        (22, False, False, (False, True, True)),  # 37, 50, 63 vs 36, 72, 108
        # a dense word and a one-byte word: chain 72 plain, 44 reduced
        (33, True, False, (False, True, True)),  # 75, 84, 93 vs 72, 144, 216
        (33, True, True, (False, True, True)),  # 75, 84, 93 vs 44, 88, 132
        (33, False, False, (True, True, True)),  # 48, 61, 74 vs 72, 144, 216
        (33, False, True, (False, True, True)),  # 48, 61, 74 vs 44, 88, 132
        # two dense words: chain 72; the exact item is word-aligned, no tail store
        (64, True, False, (False, True, True)),  # 75, 84, 93 vs 72, 144, 216
        (64, True, True, (False, True, True)),
        (64, False, False, (False, True, True)),
        (64, False, True, (False, True, True)),
        # three dense words: chain 108
        (96, True, False, (True, True, True)),  # 107, 116, 125 vs 108, 216, 324
        (96, True, True, (True, True, True)),
        (96, False, False, (True, True, True)),
        (96, False, True, (True, True, True)),
    ],
)
def test_should_codecopy_by_uses(n, padded, reduced, expected):
    for uses, expected_for_uses in enumerate(expected, start=1):
        assert should_codecopy(DENSE[:n], padded, reduced, uses) is expected_for_uses


def _runtime_venom(code: str, level: OptimizationLevel):
    settings = Settings(experimental_codegen=True, optimize=level)
    compiler_data = CompilerData(code, settings=settings)
    # `_opt_codesize()` reads the global settings, like the compiler driver
    with anchor_settings(compiler_data.settings):
        return generate_runtime_venom(compiler_data.global_ctx, compiler_data.settings)


def _deploy_venom(code: str, level: OptimizationLevel):
    settings = Settings(experimental_codegen=True, optimize=level)
    compiler_data = CompilerData(code, settings=settings)
    with anchor_settings(compiler_data.settings):
        return generate_deploy_venom(
            compiler_data.global_ctx, compiler_data.settings, b"\x00" * 32, 0
        )


def _literal_sections(ctx):
    return [s for s in ctx.data_segment if s.label.value.endswith("_literal")]


def _instructions(ctx):
    return [inst for bb in ctx.get_basic_blocks() for inst in bb.instructions]


def _codecopies(ctx, section):
    copies = [inst for inst in _instructions(ctx) if inst.opcode == "codecopy"]
    return [inst for inst in copies if inst.operands[1] == section.label]


def _length_stores(ctx, n):
    stores = [inst for inst in _instructions(ctx) if inst.opcode == "mstore"]
    return [inst for inst in stores if inst.operands[0] == IRLiteral(n)]


def _words(data):
    padded = data.ljust(ceil32(len(data)), b"\x00")
    return [int.from_bytes(padded[i : i + 32], "big") for i in range(0, len(padded), 32)]


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
    (codecopy,) = _codecopies(ctx, section)
    _check_literal_copy(codecopy, n, expected_item)


def _check_literal_copy(codecopy, n, expected_item):
    size, _, _ = codecopy.operands
    assert size == IRLiteral(len(expected_item))

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


def _check_literal_chain(length_store, data):
    # the chain sits right before the length store: `add ptr, 32 + i`
    # then the `mstore` of the word, for every word of the padded data
    words = _words(data)
    bb = length_store.parent.instructions
    idx = bb.index(length_store)
    chain = bb[idx - 2 * len(words) : idx]
    ptr = length_store.operands[1]
    assert [inst.opcode for inst in chain] == ["add", "mstore"] * len(words)
    adds, stores = chain[0::2], chain[1::2]
    assert [inst.operands for inst in adds] == [
        [IRLiteral(32 + i), ptr] for i in range(0, len(words) * 32, 32)
    ]
    assert [inst.operands for inst in stores] == [
        [IRLiteral(word), add.output] for word, add in zip(words, adds)
    ]
    # nothing else writes into the literal's data (the tail store is gone)
    offsets = [inst.output for inst in bb if inst.opcode == "add" and inst.operands[1] == ptr]
    data_stores = [inst for inst in bb if inst.opcode == "mstore" and inst.operands[1] in offsets]
    assert data_stores == stores
    # nothing of the copy survives the rewrite: every offset into the
    # buffer has a use
    used = {op for inst in bb for op in inst.operands}
    assert all(offset in used for offset in offsets)


# revert reasons use the exact item even at gas levels, other literals keep
# the padded one
@pytest.mark.parametrize("revert_kind", ["assert", "raise", "custom_error"])
# 40 bytes: the returned literal stays a chain (75 vs 72 bytes)
@pytest.mark.parametrize("n,returned_copied", [(40, False), (100, True)])
def test_revert_reason_literal_exact_item_at_gas_level(revert_kind, n, returned_copied):
    msg = ALPHABET[:n]
    revert_stmt = {
        "assert": f'assert x == 0, "{msg}"',
        "raise": f'if x != 0:\n        raise "{msg}"',
        "custom_error": f'assert x == 0, Failed(reason="{msg}")',
    }[revert_kind]
    code = f"""
error Failed:
    reason: String[{n}]

@external
def foo(x: uint256) -> String[{n}]:
    {revert_stmt}
    return "{msg}"
    """
    ctx = _runtime_venom(code, OptimizationLevel.GAS)

    expected_items = [msg.encode()]
    if returned_copied:
        expected_items.append(msg.encode().ljust(ceil32(n), b"\x00"))
    sections = _literal_sections(ctx)
    assert [s.data_items[0].data for s in sections] == expected_items
    for section, expected_item in zip(sections, expected_items):
        (codecopy,) = _codecopies(ctx, section)
        _check_literal_copy(codecopy, n, expected_item)


def test_padded_and_exact_items_of_one_literal_do_not_share():
    # the revert payload copies the exact bytes and the returned value the
    # word-padded ones; the items differ, so each gets its own section
    msg = ALPHABET[:100]
    code = f"""
@external
def foo(x: uint256) -> String[100]:
    assert x == 0, "{msg}"
    return "{msg}"
    """
    ctx = _runtime_venom(code, OptimizationLevel.GAS)
    exact, padded = _literal_sections(ctx)
    assert exact.data_items[0].data == msg.encode()
    assert padded.data_items[0].data == msg.encode().ljust(128, b"\x00")
    (exact_copy,) = _codecopies(ctx, exact)
    (padded_copy,) = _codecopies(ctx, padded)
    assert exact_copy is not padded_copy


@pytest.mark.parametrize("level", [OptimizationLevel.GAS, OptimizationLevel.CODESIZE])
def test_literal_below_size_threshold_keeps_mstore_chain(level):
    # two words: 75 vs 72 bytes at gas levels, 78 vs 72 at codesize levels;
    # the copy is rewritten into the chain and its item is not kept
    s = ALPHABET[:63]
    code = f"""
@external
def foo() -> String[63]:
    return "{s}"
    """
    ctx = _runtime_venom(code, level)
    assert len(_literal_sections(ctx)) == 0
    assert not any(inst.opcode == "codecopy" for inst in _instructions(ctx))
    (length_store,) = _length_stores(ctx, 63)
    _check_literal_chain(length_store, s.encode())


def test_empty_literal_keeps_only_its_length_store():
    # no data words: the rewrite leaves nothing of the copy behind
    code = """
@external
def foo():
    x: Bytes[32] = b""
    """
    ctx = _runtime_venom(code, OptimizationLevel.GAS)
    assert len(_literal_sections(ctx)) == 0
    assert not any(inst.opcode == "codecopy" for inst in _instructions(ctx))
    # the literal's buffer holds the length word only
    (buffer,) = [
        inst
        for inst in _instructions(ctx)
        if inst.opcode == "alloca" and inst.operands == [IRLiteral(32)]
    ]
    (length_store,) = [inst for inst in _length_stores(ctx, 0) if inst.operands[1] == buffer.output]
    _check_literal_chain(length_store, b"")


# a reason used three times: len + 2 + 3 * 13 bytes as copies of one
# exact item against three chains
@pytest.mark.parametrize(
    "msg,level,copied",
    [
        # 8 bytes: chains of 36 (PUSH32) at gas levels, of 15 (PUSH8, PUSH1,
        # SHL) at codesize levels
        ("overflow", OptimizationLevel.GAS, True),
        ("overflow", OptimizationLevel.CODESIZE, False),
        # 15 bytes: chains of 22 (PUSH15, PUSH1, SHL). O3 merges the three
        # identical revert tails into one site, so the item is priced for
        # one copy: 30 against 22
        (ALPHABET[:15], OptimizationLevel.CODESIZE, True),
        (ALPHABET[:15], OptimizationLevel.O3, False),
    ],
)
def test_short_revert_reason_used_three_times(msg, level, copied):
    code = f"""
@external
def foo(x: uint256) -> uint256:
    assert x != 1, "{msg}"
    assert x != 2, "{msg}"
    assert x != 3, "{msg}"
    return x
    """
    ctx = _runtime_venom(code, level)
    copies = [inst for inst in _instructions(ctx) if inst.opcode == "codecopy"]
    length_stores = _length_stores(ctx, len(msg))
    assert len(length_stores) == 3
    if copied:
        (section,) = _literal_sections(ctx)
        assert section.data_items[0].data == msg.encode()
        assert len(copies) == 3
        assert _codecopies(ctx, section) == copies
        for codecopy in copies:
            _check_literal_copy(codecopy, len(msg), msg.encode())
    else:
        assert len(_literal_sections(ctx)) == 0
        assert len(copies) == 0
        for length_store in length_stores:
            _check_literal_chain(length_store, msg.encode())


@pytest.mark.parametrize("value_first", [True, False])
def test_revert_uses_of_one_item_are_counted_per_use(value_first):
    # a word-aligned 32-byte string: the padded item of the value use and
    # the exact item of the reasons are the same bytes, so the three uses
    # share one entry. O3 merges the two revert tails into one site, so
    # the entry is priced for 1 + 1 copies: 32 + 2 + 2 * 9 = 52 against
    # two chains of 36, whichever use is lowered first
    s = ALPHABET[:32]
    value = f's: String[32] = "{s}"'
    reverts = f'assert x != 1, "{s}"\n    assert x != 2, "{s}"'
    first, second = (value, reverts) if value_first else (reverts, value)
    code = f"""
@external
def foo(x: uint256) -> String[32]:
    {first}
    {second}
    return s
    """
    ctx = _runtime_venom(code, OptimizationLevel.O3)
    (section,) = _literal_sections(ctx)
    assert section.data_items[0].data == s.encode()
    assert len(_codecopies(ctx, section)) == 3


def test_same_literal_in_two_functions_shares_one_section():
    s = ALPHABET[:96]
    code = f"""
@external
def foo() -> String[96]:
    return "{s}"

@external
def bar() -> String[96]:
    return "{s}"
    """
    ctx = _runtime_venom(code, OptimizationLevel.CODESIZE)
    (section,) = _literal_sections(ctx)
    (item,) = section.data_items
    assert item.data == s.encode()
    copies = [inst for inst in _instructions(ctx) if inst.opcode == "codecopy"]
    assert len(copies) == 2
    assert _codecopies(ctx, section) == copies
    for codecopy in copies:
        _check_literal_copy(codecopy, 96, s.encode())


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


def test_literal_in_constructor_and_runtime_one_item_per_segment():
    # deploy and runtime code are separate segments with separate pools
    s = ALPHABET[:96]
    code = f"""
s: public(String[96])

@deploy
def __init__():
    self.s = "{s}"

@external
def foo() -> String[96]:
    return "{s}"
    """
    level = OptimizationLevel.CODESIZE
    for ctx in (_runtime_venom(code, level), _deploy_venom(code, level)):
        (section,) = _literal_sections(ctx)
        assert section.data_items[0].data == s.encode()
        (codecopy,) = _codecopies(ctx, section)
        _check_literal_copy(codecopy, 96, s.encode())

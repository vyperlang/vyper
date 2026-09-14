"""
Constant bytestrings of one code segment: their data items, and code
size estimates for materializing one in memory as a `codecopy` from
its item versus a chain of `mstore`s of literal words. Used by
`VenomCodegenContext.const_bytestring_value`.

The estimates are biased so that a wrong guess can only keep the chain:
the chain is priced with the cheapest literal encoding the optimization
level can produce and PUSH1 addresses, the codecopy with a PUSH2 label.
"""

from dataclasses import dataclass, field
from typing import Optional

from vyper.compiler.settings import OptimizationLevel, get_global_settings
from vyper.utils import ceil32, evm_not
from vyper.venom import OPTIMIZATION_PASSES
from vyper.venom.basicblock import IRInstruction, IRLabel, IRLiteral, IRVariable
from vyper.venom.builder import VenomBuilder
from vyper.venom.context import IRContext
from vyper.venom.passes import ReduceLiteralsCodesize

WORD = 32

# PUSH1 <address> for every store in the chain
_ADDR_COST = 2
# PUSH1 <size>, PUSH1 <dst>, PUSH2 <label>, SWAP1, CODECOPY
_CODECOPY_COST = 2 + 2 + 3 + 1 + 1
# PUSH0, PUSH1 <address>, MSTORE zeroing the last data word
_TAIL_STORE_COST = 4


def _nbytes(val: int) -> int:
    return (val.bit_length() + 7) // 8


def push_cost(word: int, reduced: bool) -> int:
    """
    Bytes of the cheapest encoding of a word: PUSHn, and when `reduced`
    (the level runs `ReduceLiteralsCodesize`) also PUSH + NOT or
    PUSH + PUSH1 + SHL.
    """
    assert 0 <= word < 2**256
    cost = 1 + _nbytes(word)
    if not reduced:
        return cost
    cost = min(cost, 1 + _nbytes(evm_not(word)) + 1)
    if word != 0:
        trailing_zero_bytes = ((word & -word).bit_length() - 1) // 8
        if trailing_zero_bytes > 0:
            cost = min(cost, 1 + _nbytes(word >> (8 * trailing_zero_bytes)) + 2 + 1)
    return cost


def _words(data: bytes) -> list[int]:
    padded = data.ljust(ceil32(len(data)), b"\x00")
    return [int.from_bytes(padded[i : i + WORD], "big") for i in range(0, len(padded), WORD)]


def chain_bytes(data: bytes, reduced: bool) -> int:
    """Code bytes for storing `data` word by word (the length word excluded)."""
    return sum(push_cost(word, reduced) + _ADDR_COST + 1 for word in _words(data))


def codecopy_bytes(length: int, padded: bool, uses: int) -> int:
    """
    Code plus data bytes for copying a `length`-byte literal from its
    data item `uses` times. `padded` items hold whole words; exact items
    need the last word zeroed before each copy unless the length is
    word-aligned.
    """
    if padded:
        return ceil32(length) + uses * _CODECOPY_COST
    tail_store = _TAIL_STORE_COST if length % WORD != 0 else 0
    return length + uses * (_CODECOPY_COST + tail_store)


def should_codecopy(data: bytes, padded: bool, reduced: bool, uses: int) -> bool:
    """
    Whether `data`, materialized `uses` times, is estimated to be smaller
    as codecopies from one data item than as mstore chains (`reduced`:
    see `push_cost`).

    Runtime gas: the chain costs at least 8 gas per word, the codecopy
    15 + 3 gas per word, so from 3 words up the padded copy is never
    worse. A shorter literal passes the size gate only when it is used
    more than once, and then costs up to 10 gas more per use.
    """
    return codecopy_bytes(len(data), padded, uses) < uses * chain_bytes(data, reduced)


def reduced_pushes() -> bool:
    """Whether the pipeline rewrites literals into the NOT/SHL forms (O3, Os)."""
    settings = get_global_settings()
    assert settings is not None
    level = settings.optimize
    if level is None:
        # unset means the default level
        level = OptimizationLevel.default()
    passes = OPTIMIZATION_PASSES[level]
    return any((p[0] if isinstance(p, tuple) else p) is ReduceLiteralsCodesize for p in passes)


@dataclass
class _LiteralUse:
    # the literal's buffer, the length word included
    ptr: IRVariable
    codecopy: IRInstruction
    tail_store: Optional[IRInstruction]


@dataclass
class _LiteralEntry:
    label: IRLabel
    item: bytes
    data: bytes
    padded: bool
    uses: list[_LiteralUse] = field(default_factory=list)


class LiteralPool:
    """
    The literal data items of one code segment (deploy and runtime code
    keep separate pools). Identical items share one label. Every literal
    is lowered as a codecopy; once the segment is lowered and the use
    count of each item is known, `finalize` appends the data sections of
    the items that pay for themselves and rewrites the other copies into
    mstore chains.
    """

    def __init__(self) -> None:
        self._entries: dict[bytes, _LiteralEntry] = {}
        self._finalized = False

    def use(self, builder: VenomBuilder, ptr: IRVariable, data: bytes, padded: bool) -> None:
        """
        Copy `data` behind the length word of the buffer at `ptr` from
        its data item, `padded` to whole words or exact.
        """
        assert not self._finalized
        item = data
        if padded:
            item = data.ljust(ceil32(len(data)), b"\x00")
        entry = self._entries.get(item)
        if entry is None:
            label = IRLabel(builder.ctx.get_next_label("literal").value, is_symbol=True)
            entry = _LiteralEntry(label, item, data, padded)
            self._entries[item] = entry

        tail_store = None
        if len(item) % WORD != 0:
            # zero the last data word before the copy so the tail padding
            # matches what the mstore chain writes
            last_word = builder.add(ptr, IRLiteral(WORD + len(item) - len(item) % WORD))
            builder.mstore(last_word, IRLiteral(0))
            tail_store = builder.get_last_inst("mstore")

        data_ptr = builder.add(ptr, IRLiteral(WORD))
        builder.codecopy(data_ptr, entry.label, IRLiteral(len(item)))
        entry.uses.append(_LiteralUse(ptr, builder.get_last_inst("codecopy"), tail_store))

    def finalize(self, ctx: IRContext, reduced: bool) -> None:
        """
        Append the data sections of the items whose copies are smaller
        than the chains they replace and rewrite the other copies into
        chains (`reduced`: see `push_cost`).
        """
        assert not self._finalized
        self._finalized = True
        for entry in self._entries.values():
            if should_codecopy(entry.data, entry.padded, reduced, len(entry.uses)):
                # known limitation: if every use of the item turns out to
                # be dead, dead store elimination removes the codecopies
                # but the item stays in the bytecode
                ctx.append_data_section(entry.label)
                ctx.append_data_item(entry.item)
            else:
                for use in entry.uses:
                    _rewrite_as_chain(use, entry.data)


def _rewrite_as_chain(use: _LiteralUse, data: bytes) -> None:
    """Replace the copy (and tail store) of a use with the mstore chain."""
    bb = use.codecopy.parent
    assert use.codecopy in bb.instructions
    index = bb.instructions.index(use.codecopy)
    for i, word in enumerate(_words(data)):
        offset = bb.parent.get_next_variable()
        add = IRInstruction("add", [IRLiteral(WORD + WORD * i), use.ptr], [offset])
        mstore = IRInstruction("mstore", [IRLiteral(word), offset])
        for inst in (add, mstore):
            bb.insert_instruction(inst, index)
            # the chain takes over the source position of the copy
            inst.ast_source = use.codecopy.ast_source
            inst.error_msg = use.codecopy.error_msg
            index += 1
    bb.remove_instruction(use.codecopy)
    if use.tail_store is not None:
        assert use.tail_store.parent is bb
        bb.remove_instruction(use.tail_store)

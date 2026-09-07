"""
Code size estimates for materializing a constant bytestring in memory:
a chain of `mstore`s of literal words versus a `codecopy` from a data
section holding the bytes. Used by `VenomCodegenContext.const_bytestring_value`.

The estimates are biased so that a wrong guess can only keep the chain:
the chain is priced with the cheapest literal encoding available to
`ReduceLiteralsCodesize` at any optimization level and PUSH1 addresses,
the codecopy with a PUSH2 label.
"""

from vyper.utils import ceil32, evm_not

WORD = 32

# PUSH1 <address> for every store in the chain
_ADDR_COST = 2
# PUSH1 <size>, PUSH1 <dst>, PUSH2 <label>, SWAP1, CODECOPY
_CODECOPY_COST = 2 + 2 + 3 + 1 + 1
# PUSH0, PUSH1 <address>, MSTORE zeroing the last data word
_TAIL_STORE_COST = 4


def _nbytes(val: int) -> int:
    return (val.bit_length() + 7) // 8


def push_cost(word: int) -> int:
    """
    Bytes of the cheapest encoding of a word: PUSHn, PUSH + NOT, or
    PUSH + PUSH1 + SHL (the forms `ReduceLiteralsCodesize` produces).
    """
    assert 0 <= word < 2**256
    cost = 1 + _nbytes(word)
    cost = min(cost, 1 + _nbytes(evm_not(word)) + 1)
    if word != 0:
        trailing_zero_bytes = ((word & -word).bit_length() - 1) // 8
        if trailing_zero_bytes > 0:
            cost = min(cost, 1 + _nbytes(word >> (8 * trailing_zero_bytes)) + 2 + 1)
    return cost


def chain_bytes(data: bytes) -> int:
    """Code bytes for storing `data` word by word (the length word excluded)."""
    padded = data.ljust(ceil32(len(data)), b"\x00")
    words = [int.from_bytes(padded[i : i + WORD], "big") for i in range(0, len(padded), WORD)]
    return sum(push_cost(word) + _ADDR_COST + 1 for word in words)


def codecopy_bytes(length: int, padded: bool) -> int:
    """
    Code plus data bytes for copying a `length`-byte literal from the
    data section. `padded` items hold whole words; exact items need the
    last word zeroed first unless the length is word-aligned.
    """
    if padded:
        return ceil32(length) + _CODECOPY_COST
    tail_store = _TAIL_STORE_COST if length % WORD != 0 else 0
    return length + _CODECOPY_COST + tail_store


def should_codecopy(data: bytes, padded: bool) -> bool:
    """
    Whether `data` is estimated to be smaller as a codecopy than as an
    mstore chain. A single word is never worth a data section.

    Runtime gas cannot get worse in the padded form: the chain costs at
    least 8 gas per word, the codecopy 15 + 3 gas per word, and the size
    gate only passes for 3 words or more (2 dense words: 73 vs 72 bytes).
    """
    if len(data) <= WORD:
        return False
    return codecopy_bytes(len(data), padded) < chain_bytes(data)

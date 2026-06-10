"""
Constants used throughout codegen_venom.
"""

from __future__ import annotations

from vyper.utils import IDENTITY_PRECOMPILE as IDENTITY_PRECOMPILE  # noqa: F401

# ABI encoding
SELECTOR_BYTES = 4
SELECTOR_SHIFT_BITS = 224  # 256 - 32, right-align 4-byte selector in 32-byte word

# EVM precompile addresses
ECRECOVER_PRECOMPILE = 0x01
SHA256_PRECOMPILE = 0x02

# EVM limits
BLOCKHASH_LOOKBACK_LIMIT = 256  # max blocks accessible via BLOCKHASH opcode

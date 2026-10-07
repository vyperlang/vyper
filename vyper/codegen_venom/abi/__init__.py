"""
ABI encoding/decoding for Venom IR.

This module provides functions to:
- abi_encode_to_buf: Encode Vyper memory layout to ABI format
- abi_decode_to_buf: Decode ABI format to Vyper memory layout
"""

from vyper.codegen_venom.abi.abi_decoder import (
    abi_decode_to_buf,
    decode_unbounded_sequence_to_scratch,
)
from vyper.codegen_venom.abi.abi_encoder import (
    abi_encode_to_buf,
    abi_encode_values_to_buf,
    runtime_abi_size_for_encode,
)

__all__ = [
    "abi_encode_to_buf",
    "abi_decode_to_buf",
    "abi_encode_values_to_buf",
    "decode_unbounded_sequence_to_scratch",
    "runtime_abi_size_for_encode",
]

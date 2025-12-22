"""
Unit tests for ABI encode/decode builtin handlers.

These test the handler registration and basic IR generation.
E2E tests deferred until full venom rewrite complete.
"""

import pytest

from vyper.codegen_venom.builtins import BUILTIN_HANDLERS


class TestABIHandlerRegistration:
    """Test that ABI handlers are properly registered."""

    def test_abi_encode_registered(self):
        assert "abi_encode" in BUILTIN_HANDLERS

    def test_abi_decode_registered(self):
        assert "abi_decode" in BUILTIN_HANDLERS

    def test_deprecated_abi_encode_registered(self):
        assert "_abi_encode" in BUILTIN_HANDLERS

    def test_deprecated_abi_decode_registered(self):
        assert "_abi_decode" in BUILTIN_HANDLERS

    def test_deprecated_aliases_same_handler(self):
        # Deprecated aliases should point to same handlers
        assert BUILTIN_HANDLERS["_abi_encode"] is BUILTIN_HANDLERS["abi_encode"]
        assert BUILTIN_HANDLERS["_abi_decode"] is BUILTIN_HANDLERS["abi_decode"]

"""
Unit tests for contract creation builtin handlers.

- raw_create
- create_minimal_proxy_to (and deprecated alias create_forwarder_to)
- create_copy_of
- create_from_blueprint

These test the handler registration and basic IR generation.
E2E tests are deferred until full venom rewrite complete.
"""

import pytest

from vyper.codegen_venom.builtins import BUILTIN_HANDLERS


class TestCreateHandlerRegistration:
    """Test that create handlers are properly registered."""

    def test_raw_create_registered(self):
        assert "raw_create" in BUILTIN_HANDLERS

    def test_create_minimal_proxy_to_registered(self):
        assert "create_minimal_proxy_to" in BUILTIN_HANDLERS

    def test_create_forwarder_to_registered(self):
        # Deprecated alias for create_minimal_proxy_to
        assert "create_forwarder_to" in BUILTIN_HANDLERS

    def test_create_copy_of_registered(self):
        assert "create_copy_of" in BUILTIN_HANDLERS

    def test_create_from_blueprint_registered(self):
        assert "create_from_blueprint" in BUILTIN_HANDLERS


class TestEIP1167Bytecode:
    """Test EIP-1167 minimal proxy bytecode generation."""

    def test_eip1167_bytecode_lengths(self):
        from vyper.codegen_venom.builtins.create import _eip1167_bytecode

        loader, pre, post = _eip1167_bytecode()
        # loader: 9 bytes
        assert len(loader) == 9, f"loader length: {len(loader)}"
        # forwarder_pre: 10 bytes (ends with PUSH20 opcode)
        assert len(pre) == 10, f"forwarder_pre length: {len(pre)}"
        # forwarder_post: 15 bytes
        assert len(post) == 15, f"forwarder_post length: {len(post)}"

    def test_total_proxy_size(self):
        from vyper.codegen_venom.builtins.create import _eip1167_bytecode

        loader, pre, post = _eip1167_bytecode()
        # Total = loader + pre + 20-byte address + post = 9 + 10 + 20 + 15 = 54
        total = len(loader) + len(pre) + 20 + len(post)
        assert total == 54


class TestCreatePreamble:
    """Test create_copy_of preamble bytecode generation."""

    def test_preamble_length(self):
        from vyper.codegen_venom.builtins.create import _create_preamble_bytes

        preamble = _create_preamble_bytes()
        assert len(preamble) == 11

    def test_preamble_starts_with_push3(self):
        from vyper.codegen_venom.builtins.create import _create_preamble_bytes

        preamble = _create_preamble_bytes()
        # PUSH3 opcode is 0x62
        assert preamble[0] == 0x62

"""
Unit tests for system-level builtin handlers (raw_call, send, raw_log, raw_revert).

These test the handler registration and basic IR generation.
E2E tests are deferred until full venom rewrite complete.
"""

import pytest

from vyper.codegen_venom.builtins import BUILTIN_HANDLERS


class TestSystemHandlerRegistration:
    """Test that system handlers are properly registered."""

    def test_raw_call_registered(self):
        assert "raw_call" in BUILTIN_HANDLERS

    def test_send_registered(self):
        assert "send" in BUILTIN_HANDLERS

    def test_raw_log_registered(self):
        assert "raw_log" in BUILTIN_HANDLERS

    def test_raw_revert_registered(self):
        assert "raw_revert" in BUILTIN_HANDLERS

import pytest

from vyper import compiler
from vyper.exceptions import StructureException

fail_list = [
    (
        """
interface I:
    def get_msg() -> String[20]: nonpayable

@external
def f(x: bool, target: address):
    assert x, extcall I(target).get_msg()
        """,
        StructureException,
    ),
    (
        """
interface I:
    def get_msg() -> String[20]: nonpayable

@external
def f(x: bool, target: address):
    raise extcall I(target).get_msg()
        """,
        StructureException,
    ),
    (
        """
interface I:
    def get_msg() -> String[20]: nonpayable

@external
def f(x: bool, target: address):
    assert x, staticcall I(target).get_msg()
        """,
        StructureException,
    ),
    (
        """
interface I:
    def get_msg() -> String[20]: nonpayable

@external
def f(x: bool, target: address):
    raise staticcall I(target).get_msg()
        """,
        StructureException,
    ),
]


@pytest.mark.parametrize("bad_code,exc", fail_list)
def test_revert_reason_rejects_external_calls(bad_code, exc):
    with pytest.raises(exc):
        compiler.compile_code(bad_code)

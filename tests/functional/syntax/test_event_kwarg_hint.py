import warnings

from vyper.compiler import compile_code


def test_event_kwarg_hint():
    code = """
from ethereum.ercs import IERC20

def foo():
    log IERC20.Transfer(msg.sender, msg.sender, 123)
    """

    with warnings.catch_warnings(record=True) as w:
        assert compile_code(code) is not None

    expected = "Instantiating events with positional arguments is deprecated "
    expected += "as of v0.4.1 and will be disallowed in a future release. "
    expected += "Use kwargs instead e.g.:\n"
    expected += "```\nlog IERC20.Transfer(sender=msg.sender, receiver=msg.sender, value=123)\n```"

    assert len(w) == 1, [s.message for s in w]
    assert str(w[0].message).startswith(expected)


def test_event_hint_single_char_argument():
    code = """
from ethereum.ercs import IERC20

def foo():
    log IERC20.Transfer(msg.sender, msg.sender, 1)
    """

    with warnings.catch_warnings(record=True) as w:
        assert compile_code(code) is not None

    expected = "Instantiating events with positional arguments is deprecated "
    expected += "as of v0.4.1 and will be disallowed in a future release. "
    expected += "Use kwargs instead e.g.:\n"
    expected += "```\nlog IERC20.Transfer(sender=msg.sender, receiver=msg.sender, value=1)\n```"

    assert len(w) == 1, [s.message for s in w]
    assert str(w[0].message).startswith(expected)


def test_no_arg_no_hint():
    # test that logging events with 0 args does not emit a warning
    code = """
event MyLog:
    pass

@external
def foo():
    log MyLog()
    """

    with warnings.catch_warnings(record=True) as w:
        assert compile_code(code) is not None

    assert len(w) == 0

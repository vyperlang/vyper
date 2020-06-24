from pytest import raises

from vyper.exceptions import VyperException


def test_type_exception_pos():
    pos = (1, 2)

    with raises(VyperException) as e:
        raise VyperException("Fail!", pos)

    assert e.value.lineno == 1
    assert e.value.col_offset == 2
    assert str(e.value) == "line 1:2 Fail!"

from pytest import raises

from viper.exceptions import ParserException


def test_type_exception_pos():
    pos = (1, 2)

    with raises(ParserException) as e:
        raise ParserException('Fail!', pos)

    assert e.value.lineno == 1
    assert e.value.col_offset == 2
    assert str(e.value) == 'line 1:2 Fail!'

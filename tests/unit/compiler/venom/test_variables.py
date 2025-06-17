from vyper.venom.basicblock import IRVariable


def test_variable_equality():
    v1 = IRVariable("%x")
    v2 = IRVariable("%x")
    assert v1 == v2
    assert v1 != IRVariable("%y")

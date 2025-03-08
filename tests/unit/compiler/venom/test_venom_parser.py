from tests.venom_utils import parse_from_basic_block
from vyper.venom.check_venom import VenomSemanticErrorType, check_venom


def test_venom_parser():
    code = """
    main:
        %1 = 1
        ret %1
    """

    ctx = parse_from_basic_block(code)
    errors = check_venom(ctx)

    assert errors == []


def test_venom_parser_not_terminated():
    """
    Test if the venom check finds the unterminated
    basic blocks
    """
    code = """
    bb0:
        %1 = 1
    bb1:
        jmp @bb0
    bb2:
        stop
    bb3:
        calldataload 10, 20, 30
    """

    ctx = parse_from_basic_block(code)
    errors = check_venom(ctx)

    all(e.error_type == VenomSemanticErrorType.NotTerminatedBasicBlock for e in errors)
    assert len(errors) == 2
    assert list(e.metadata.label.name for e in errors) == ["bb0", "bb3"]


def test_venom_parser_nonexistant_var():
    """
    Test use of undefined variable
    """
    code = """
    main:
        ret %1
    """

    ctx = parse_from_basic_block(code)
    errors = check_venom(ctx)

    assert len(errors) == 1


def test_venom_parser_nonexistant_var2():
    """
    Test definition of variable is not always reached
    """
    code = """
    main:
        %par = param
        %1 = 1
        jnz %par, @br1, @br2
    br1:
        %2 = 2
        jmp @join
    br2:
        %3 = 3
        jmp @join
    join:
        ret %1, %2, %3
    """

    ctx = parse_from_basic_block(code)
    errors = check_venom(ctx)

    assert len(errors) == 2
    assert {e.metadata.name for e in errors} == {"%2", "%3"}

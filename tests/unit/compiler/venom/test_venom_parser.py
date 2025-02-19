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
    code = """
    main:
        ret %1
    """

    ctx = parse_from_basic_block(code)
    errors = check_venom(ctx)

    assert len(errors) == 1

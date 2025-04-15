from tests.venom_utils import parse_from_basic_block
from vyper.venom.check_venom import BasicBlockNotTerminated, VarNotDefined, find_semantic_errors


def test_venom_parser():
    code = """
    main:
        %1 = 1
        ret %1
    """

    ctx = parse_from_basic_block(code)
    errors = find_semantic_errors(ctx)

    assert len(errors) == 0


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
    errors = find_semantic_errors(ctx)

    assert all(isinstance(err, BasicBlockNotTerminated) for err in errors)
    assert len(errors) == 2
    assert list(e.basicblock.label.name for e in errors) == ["bb0", "bb3"]


def test_venom_parser_nonexistent_var():
    """
    Test use of undefined variable
    """
    code = """
    main:
        ret %1
    """

    ctx = parse_from_basic_block(code)
    errors = find_semantic_errors(ctx)

    assert all(isinstance(err, VarNotDefined) for err in errors)
    assert len(errors) == 1
    assert [err.var.name for err in errors] == ["%1"]


def test_venom_parser_nonexistent_var2():
    """
    Test variable is not defined in all input bbs
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
        ; %2 and %3 are not defined in all input bbs(!)
        ret %1, %2, %3
    """

    ctx = parse_from_basic_block(code)
    errors = find_semantic_errors(ctx)

    assert all(isinstance(err, VarNotDefined) for err in errors)
    assert len(errors) == 2
    assert [err.var.name for err in errors] == ["%3", "%2"]
    assert [err.inst.parent.label.name for err in errors] == ["join", "join"]


def test_venom_parser_nonexistant_var_loop():
    """
    Test detecting usage of variable in loop
    body outside of loop body
    """
    code = """
    main:
        %par = param
        jmp @cond
    cond:
        %iter = phi @main, %par, @loop_body, %iter:1
        %condition = lt %iter, 100
        jnz %condition, @after, @loop_body
    loop_body:
        %var = mload %par
        %iter:1 = add 1, %iter
        jmp @cond
    after:
        sink %condition, %var
    """

    ctx = parse_from_basic_block(code)
    errors = find_semantic_errors(ctx)

    assert all(isinstance(err, VarNotDefined) for err in errors)

    assert len(errors) == 1

    assert [err.var.name for err in errors] == ["%var"]
    assert [err.inst.parent.label.name for err in errors] == ["after"]


def test_venom_parser_nonexistant_var_loop_incorrect_phi():
    """
    Test detecting incorrect phi var usage.
    The variable that is taken from main is
    not defined in main
    """
    code = """
    main:
        %par = param
        jmp @cond
    cond:
        ; incorrect phi (var is not main)
        %iter = phi @main, %var, @loop_body, %iter:1
        %condition = lt %iter, 100
        jnz %condition, @after, @loop_body
    loop_body:
        %var = mload %par
        %iter:1 = add 1, %iter
        jmp @cond
    after:
        sink %condition, %var
    """

    ctx = parse_from_basic_block(code)
    errors = find_semantic_errors(ctx)

    assert all(isinstance(err, VarNotDefined) for err in errors)

    assert len(errors) == 2

    assert [err.var.name for err in errors] == ["%var", "%var"]
    assert [err.inst.parent.label.name for err in errors] == ["cond", "after"]


def test_venom_parser_unrechable():
    """ """
    code = """
    main:
        %par = param
        jmp @after
    unreachable:
        sink %par
    after:
        sink %par
    """

    ctx = parse_from_basic_block(code)
    errors = find_semantic_errors(ctx)

    assert all(isinstance(err, VarNotDefined) for err in errors)

    assert len(errors) == 1

    assert [err.var.name for err in errors] == ["%par"]
    assert [err.inst.parent.label.name for err in errors] == ["unreachable"]

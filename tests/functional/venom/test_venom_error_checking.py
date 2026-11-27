import pytest

from tests.venom_utils import parse_from_basic_block
from vyper.codegen_venom.module import generate_venom_runtime
from vyper.compiler.phases import CompilerData
from vyper.compiler.settings import Settings, anchor_settings
from vyper.venom.check_venom import (
    BasicBlockNotTerminated,
    LogArityError,
    UnsupportedInstruction,
    VarNotDefined,
    find_semantic_errors,
)


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
        %par = source
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
        %par = source
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
        %par = source
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
        %par = source
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


def test_venom_parser_rejects_removed_memtop():
    code = """
    main:
        %ptr = memtop
        stop
    """

    ctx = parse_from_basic_block(code)
    errors = find_semantic_errors(ctx)

    assert len(errors) == 1
    assert isinstance(errors[0], UnsupportedInstruction)


def _log_code(topics: list[str], count: str) -> str:
    # text operand order is `log offset, size, topic0, ..., topic_count`
    operands = ", ".join(["%off", "%sz", *topics, count])
    return f"""
    main:
        %off = source
        %sz = 32
        %t0 = 0xaa
        %t1 = 0xbb
        %t2 = 0xcc
        %t3 = 0xdd
        %t4 = 0xee
        %c = source
        log {operands}
        sink %off, %sz, %t0, %t1, %t2, %t3, %t4, %c
    """


_TOPICS = ["%t0", "%t1", "%t2", "%t3", "%t4"]


@pytest.mark.parametrize("n", range(5))
def test_venom_log_arity_ok(n):
    ctx = parse_from_basic_block(_log_code(_TOPICS[:n], str(n)))
    assert find_semantic_errors(ctx) == []


# GH issue 5402: the assembler trusts the topic count to pick LOG0..LOG4, so
# a count that does not match the topic operands must be rejected
@pytest.mark.parametrize(
    "n_topics,count",
    [
        (1, "2"),  # too few topics (the issue's example)
        (0, "1"),
        (3, "4"),
        (1, "0"),  # too many topics
        (2, "1"),
        (4, "3"),
        (5, "4"),
        (5, "5"),  # count out of range
        (0, "-1"),
    ],
)
def test_venom_log_arity_mismatch(n_topics, count):
    ctx = parse_from_basic_block(_log_code(_TOPICS[:n_topics], count))
    errors = find_semantic_errors(ctx)

    assert len(errors) == 1
    assert isinstance(errors[0], LogArityError)


def test_venom_log_non_literal_count():
    ctx = parse_from_basic_block(_log_code(_TOPICS[:1], "%c"))
    errors = find_semantic_errors(ctx)

    assert len(errors) == 1
    assert isinstance(errors[0], LogArityError)


def test_venom_log_no_operands():
    code = """
    main:
        log
        stop
    """
    ctx = parse_from_basic_block(code)
    errors = find_semantic_errors(ctx)

    assert len(errors) == 1
    assert isinstance(errors[0], LogArityError)


def test_venom_log_arity_frontend_output():
    # logs emitted by the venom frontend (events with 0..3 indexed args,
    # i.e. LOG1..LOG4, plus raw_log with 0..4 topics) pass the check
    code = """
event E0:
    a: uint256

event E1:
    a: indexed(uint256)
    b: Bytes[64]

event E2:
    a: indexed(address)
    b: indexed(bytes32)
    c: uint256

event E3:
    a: indexed(uint256)
    b: indexed(uint256)
    c: indexed(uint256)
    d: String[32]

@external
def foo(x: uint256, d: Bytes[64]):
    log E0(a=x)
    log E1(a=x, b=d)
    log E2(a=msg.sender, b=keccak256(d), c=x)
    log E3(a=x, b=x + 1, c=x + 2, d="hello")
    raw_log([], d)
    raw_log([keccak256(d)], d)
    raw_log([keccak256(d), keccak256(d)], d)
    raw_log([keccak256(d), keccak256(d), keccak256(d)], d)
    raw_log([keccak256(d), keccak256(d), keccak256(d), keccak256(d)], d)
    """
    settings = Settings(experimental_codegen=True)
    with anchor_settings(settings):
        compiler_data = CompilerData(code, settings=settings)
        ctx = generate_venom_runtime(compiler_data.global_ctx, settings)

    log_counts = sorted(
        inst.operands[0].value
        for fn in ctx.functions.values()
        for bb in fn.get_basic_blocks()
        for inst in bb.instructions
        if inst.opcode == "log"
    )
    assert log_counts == [0, 1, 1, 2, 2, 3, 3, 4, 4]
    assert find_semantic_errors(ctx) == []

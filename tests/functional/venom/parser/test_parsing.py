from vyper.venom.basicblock import IRBasicBlock, IRInstruction, IRLabel, IRLiteral, IRVariable
from vyper.venom.context import IRContext
from vyper.venom.function import IRFunction
from vyper.venom.parser import parse_venom

# TODO: Refactor tests with these helpers


def instructions_eq(i1: IRInstruction, i2: IRInstruction) -> bool:
    return i1.output == i2.output and i1.opcode == i2.opcode and i1.operands == i2.operands


def assert_bb_eq(bb1: IRBasicBlock, bb2: IRBasicBlock):
    assert bb1.label.value == bb2.label.value
    assert len(bb1.instructions) == len(bb2.instructions)
    for i1, i2 in zip(bb1.instructions, bb2.instructions):
        assert instructions_eq(i1, i2), f"[{i1}] != [{i2}]"


def assert_fn_eq(fn1: IRFunction, fn2: IRFunction):
    assert fn1.name.value == fn2.name.value
    assert fn1.last_variable == fn2.last_variable
    assert len(fn1._basic_block_dict) == len(fn2._basic_block_dict)

    for name1, bb1 in fn1._basic_block_dict.items():
        assert name1 in fn2._basic_block_dict
        assert_bb_eq(bb1, fn2._basic_block_dict[name1])

    # check function entry is the same
    assert fn1.entry.label == fn2.entry.label


def assert_ctx_eq(ctx1: IRContext, ctx2: IRContext):
    assert ctx1.last_label == ctx2.last_label
    assert len(ctx1.functions) == len(ctx2.functions)
    for label1, fn1 in ctx1.functions.items():
        assert label1 in ctx2.functions
        assert_fn_eq(fn1, ctx2.functions[label1])

    # check entry function is the same
    assert next(iter(ctx1.functions.keys())) == next(iter(ctx2.functions.keys()))

    assert len(ctx1.data_segment) == len(ctx2.data_segment)
    for d1, d2 in zip(ctx1.data_segment, ctx2.data_segment):
        assert instructions_eq(d1, d2), f"data: [{d1}] != [{d2}]"


def test_single_bb():
    source = """
    function main {
        main:
            stop
    }

    [data]
    """

    parsed_ctx = parse_venom(source)

    expected_ctx = IRContext()
    expected_ctx.add_function(main_fn := IRFunction(IRLabel("main")))
    main_bb = main_fn.get_basic_block("main")
    main_bb.append_instruction("stop")

    assert_ctx_eq(parsed_ctx, expected_ctx)


def test_multi_bb_single_fn():
    source = """
    function start {
        start:
            %1 = callvalue
            jnz @fine, @has_callvalue, %1
        fine:
            %2 = calldataload 4
            %4 = add %2, 279387
            return %2, %4
        has_callvalue:
            revert 0, 0
    }

    [data]
    """

    parsed_ctx = parse_venom(source)

    expected_ctx = IRContext()
    expected_ctx.add_function(start_fn := IRFunction(IRLabel("start")))

    start_bb = start_fn.get_basic_block("start")
    start_bb.append_instruction("callvalue", ret=IRVariable("1"))
    start_bb.append_instruction("jnz", IRVariable("1"), IRLabel("has_callvalue"), IRLabel("fine"))

    start_fn.append_basic_block(fine_bb := IRBasicBlock(IRLabel("fine"), start_fn))
    fine_bb.append_instruction("calldataload", IRLiteral(4), ret=IRVariable("2"))
    fine_bb.append_instruction("add", IRLiteral(279387), IRVariable("2"), ret=IRVariable("4"))
    fine_bb.append_instruction("return", IRVariable("4"), IRVariable("2"))

    has_callvalue_bb = IRBasicBlock(IRLabel("has_callvalue"), start_fn)
    start_fn.append_basic_block(has_callvalue_bb)
    has_callvalue_bb.append_instruction("revert", IRLiteral(0), IRLiteral(0))
    has_callvalue_bb.append_instruction("stop")

    start_fn.last_variable = 4

    assert_ctx_eq(parsed_ctx, expected_ctx)


def test_data_section():
    parsed_ctx = parse_venom(
        """
    function entry {
        entry:
            stop
    }

    [data]
    dbname @selector_buckets
    db @selector_bucket_0
    db @fallback
    db @selector_bucket_2
    db @selector_bucket_3
    db @fallback
    db @selector_bucket_5
    db @selector_bucket_6
    """
    )

    expected_ctx = IRContext()
    expected_ctx.add_function(entry_fn := IRFunction(IRLabel("entry")))
    entry_fn.get_basic_block("entry").append_instruction("stop")

    expected_ctx.data_segment = [
        IRInstruction("dbname", [IRLabel("selector_buckets")]),
        IRInstruction("db", [IRLabel("selector_bucket_0")]),
        IRInstruction("db", [IRLabel("fallback")]),
        IRInstruction("db", [IRLabel("selector_bucket_2")]),
        IRInstruction("db", [IRLabel("selector_bucket_3")]),
        IRInstruction("db", [IRLabel("fallback")]),
        IRInstruction("db", [IRLabel("selector_bucket_5")]),
        IRInstruction("db", [IRLabel("selector_bucket_6")]),
    ]

    assert_ctx_eq(parsed_ctx, expected_ctx)


def test_multi_function():
    parsed_ctx = parse_venom(
        """
    function entry {
        entry:
            invoke @check_cv
            jmp @wow
        wow:
            mstore 0, 1
            return 0, 32
    }

    function check_cv {
        check_cv:
            %1 = callvalue
            %2 = param
            jnz @no_value, @has_value, %1
        no_value:
            ret %2
        has_value:
            revert 0, 0
    }

    [data]
    """
    )

    expected_ctx = IRContext()
    expected_ctx.add_function(entry_fn := IRFunction(IRLabel("entry")))

    entry_bb = entry_fn.get_basic_block("entry")
    entry_bb.append_instruction("invoke", IRLabel("check_cv"))
    entry_bb.append_instruction("jmp", IRLabel("wow"))

    entry_fn.append_basic_block(wow_bb := IRBasicBlock(IRLabel("wow"), entry_fn))
    wow_bb.append_instruction("mstore", IRLiteral(1), IRLiteral(0))
    wow_bb.append_instruction("return", IRLiteral(32), IRLiteral(0))

    expected_ctx.add_function(check_fn := IRFunction(IRLabel("check_cv")))

    check_entry_bb = check_fn.get_basic_block("check_cv")
    check_entry_bb.append_instruction("callvalue", ret=IRVariable("1"))
    check_entry_bb.append_instruction("param", ret=IRVariable("2"))
    check_entry_bb.append_instruction(
        "jnz", IRVariable("1"), IRLabel("has_value"), IRLabel("no_value")
    )
    check_fn.append_basic_block(no_value_bb := IRBasicBlock(IRLabel("no_value"), check_fn))
    no_value_bb.append_instruction("ret", IRVariable("2"))

    check_fn.append_basic_block(value_bb := IRBasicBlock(IRLabel("has_value"), check_fn))
    value_bb.append_instruction("revert", IRLiteral(0), IRLiteral(0))
    value_bb.append_instruction("stop")

    check_fn.last_variable = 2

    assert_ctx_eq(parsed_ctx, expected_ctx)


def test_multi_function_and_data():
    parsed_ctx = parse_venom(
        """
    function entry {
        entry:
            invoke @check_cv
            jmp @wow
        wow:
            mstore 0, 1
            return 0, 32
    }

    function check_cv {
        check_cv:
            %1 = callvalue
            %2 = param
            jnz @no_value, @has_value, %1
        no_value:
            ret %2
        has_value:
            revert 0, 0
    }

    [data]
    dbname @selector_buckets
    db @selector_bucket_0
    db @fallback
    db @selector_bucket_2
    db @selector_bucket_3
    db @selector_bucket_6
    """
    )

    expected_ctx = IRContext()
    expected_ctx.add_function(entry_fn := IRFunction(IRLabel("entry")))

    entry_bb = entry_fn.get_basic_block("entry")
    entry_bb.append_instruction("invoke", IRLabel("check_cv"))
    entry_bb.append_instruction("jmp", IRLabel("wow"))

    entry_fn.append_basic_block(wow_bb := IRBasicBlock(IRLabel("wow"), entry_fn))
    wow_bb.append_instruction("mstore", IRLiteral(1), IRLiteral(0))
    wow_bb.append_instruction("return", IRLiteral(32), IRLiteral(0))

    expected_ctx.add_function(check_fn := IRFunction(IRLabel("check_cv")))

    check_entry_bb = check_fn.get_basic_block("check_cv")
    check_entry_bb.append_instruction("callvalue", ret=IRVariable("1"))
    check_entry_bb.append_instruction("param", ret=IRVariable("2"))
    check_entry_bb.append_instruction(
        "jnz", IRVariable("1"), IRLabel("has_value"), IRLabel("no_value")
    )
    check_fn.append_basic_block(no_value_bb := IRBasicBlock(IRLabel("no_value"), check_fn))
    no_value_bb.append_instruction("ret", IRVariable("2"))

    check_fn.append_basic_block(value_bb := IRBasicBlock(IRLabel("has_value"), check_fn))
    value_bb.append_instruction("revert", IRLiteral(0), IRLiteral(0))
    value_bb.append_instruction("stop")

    check_fn.last_variable = 2

    expected_ctx.data_segment = [
        IRInstruction("dbname", [IRLabel("selector_buckets")]),
        IRInstruction("db", [IRLabel("selector_bucket_0")]),
        IRInstruction("db", [IRLabel("fallback")]),
        IRInstruction("db", [IRLabel("selector_bucket_2")]),
        IRInstruction("db", [IRLabel("selector_bucket_3")]),
        IRInstruction("db", [IRLabel("selector_bucket_6")]),
    ]

    assert_ctx_eq(parsed_ctx, expected_ctx)

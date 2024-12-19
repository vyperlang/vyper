from tests.venom_utils import assert_ctx_eq
from vyper.venom.basicblock import IRBasicBlock, IRLabel, IRLiteral, IRVariable
from vyper.venom.context import DataItem, DataSection, IRContext
from vyper.venom.function import IRFunction
from vyper.venom.parser import parse_venom


def test_single_bb():
    source = """
    function main {
        main:
            stop
    }
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
            jnz %1, @fine, @has_callvalue
        fine:
            %2 = calldataload 4
            %4 = add %2, 279387
            return %2, %4
        has_callvalue:
            revert 0, 0
    }
    """

    parsed_ctx = parse_venom(source)

    expected_ctx = IRContext()
    expected_ctx.add_function(start_fn := IRFunction(IRLabel("start")))

    start_bb = start_fn.get_basic_block("start")
    start_bb.append_instruction("callvalue", ret=IRVariable("1"))
    start_bb.append_instruction("jnz", IRVariable("1"), IRLabel("fine"), IRLabel("has_callvalue"))

    start_fn.append_basic_block(fine_bb := IRBasicBlock(IRLabel("fine"), start_fn))
    fine_bb.append_instruction("calldataload", IRLiteral(4), ret=IRVariable("2"))
    fine_bb.append_instruction("add", IRLiteral(279387), IRVariable("2"), ret=IRVariable("4"))
    fine_bb.append_instruction("return", IRVariable("4"), IRVariable("2"))

    has_callvalue_bb = IRBasicBlock(IRLabel("has_callvalue"), start_fn)
    start_fn.append_basic_block(has_callvalue_bb)
    has_callvalue_bb.append_instruction("revert", IRLiteral(0), IRLiteral(0))
    has_callvalue_bb.append_instruction("stop")

    assert_ctx_eq(parsed_ctx, expected_ctx)


def test_data_section():
    parsed_ctx = parse_venom(
        """
    function entry {
        entry:
            stop
    }

    .rodata {
        dbsection selector_buckets:
            db @selector_bucket_0
            db @fallback
            db @selector_bucket_2
            db @selector_bucket_3
            db @fallback
            db @selector_bucket_5
            db @selector_bucket_6
    }
    """
    )

    expected_ctx = IRContext()
    expected_ctx.add_function(entry_fn := IRFunction(IRLabel("entry")))
    entry_fn.get_basic_block("entry").append_instruction("stop")

    expected_ctx.data_segment = [
        DataSection(
            IRLabel("selector_buckets"),
            [
                DataItem(IRLabel("selector_bucket_0")),
                DataItem(IRLabel("fallback")),
                DataItem(IRLabel("selector_bucket_2")),
                DataItem(IRLabel("selector_bucket_3")),
                DataItem(IRLabel("fallback")),
                DataItem(IRLabel("selector_bucket_5")),
                DataItem(IRLabel("selector_bucket_6")),
            ],
        )
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
            jnz %1, @has_value, @no_value
        no_value:
            ret %2
        has_value:
            revert 0, 0
    }
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
            jnz %1, @has_value, @no_value
        no_value:
            ret %2
        has_value:
            revert 0, 0
    }

    .rodata {
        dbsection selector_buckets:
            db @selector_bucket_0
            db @fallback
            db @selector_bucket_2
            db @selector_bucket_3
            db @selector_bucket_6
    }
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

    expected_ctx.data_segment = [
        DataSection(
            IRLabel("selector_buckets"),
            [
                DataItem(IRLabel("selector_bucket_0")),
                DataItem(IRLabel("fallback")),
                DataItem(IRLabel("selector_bucket_2")),
                DataItem(IRLabel("selector_bucket_3")),
                DataItem(IRLabel("selector_bucket_6")),
            ],
        )
    ]

    assert_ctx_eq(parsed_ctx, expected_ctx)

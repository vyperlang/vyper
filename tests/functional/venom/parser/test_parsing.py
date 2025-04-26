from tests.venom_utils import assert_bb_eq, assert_ctx_eq
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


def test_hex_literal():
    source = """
    function main {
        main:
            mstore 0, 0x7  ; test odd-length literal
            mstore 1, 0x03
    }
    """

    parsed_ctx = parse_venom(source)

    expected_ctx = IRContext()
    expected_ctx.add_function(main_fn := IRFunction(IRLabel("main")))
    main_bb = main_fn.get_basic_block("main")
    main_bb.append_instruction("mstore", IRLiteral(7), IRLiteral(0))
    main_bb.append_instruction("mstore", IRLiteral(3), IRLiteral(1))

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

    assert_ctx_eq(parsed_ctx, expected_ctx)


def test_data_section():
    parsed_ctx = parse_venom(
        """
    function entry {
        entry:
            stop
    }

    data readonly {
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

    data readonly {
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


def test_phis():
    # @external
    # def _loop() -> uint256:
    #    res: uint256 = 9
    #    for i: uint256 in range(res, bound=10):
    #        res = res + i
    # return res
    source = """
    function __main_entry {
      __main_entry:  ; IN=[] OUT=[fallback, 1_then] => {}
        %27 = 0
        %1 = calldataload %27
        %28 = %1
        %29 = 224
        %2 = shr %29, %28
        %31 = %2
        %30 = 1729138561
        %4 = xor %30, %31
        %32 = %4
        jnz %32, @fallback, @1_then
        ; (__main_entry)


      1_then:  ; IN=[__main_entry] OUT=[4_condition] => {%11, %var8_0}
        %6 = callvalue
        %33 = %6
        %7 = iszero %33
        %34 = %7
        assert %34
        %var8_0 = 9
        %11 = 0
        nop
        jmp @4_condition
        ; (__main_entry)


      4_condition:  ; IN=[1_then, 5_body] OUT=[5_body, 7_exit] => {%11:3, %var8_0:2}
        %var8_0:2 = phi @1_then, %var8_0, @5_body, %var8_0:3
        %11:3 = phi @1_then, %11, @5_body, %11:4
        %35 = %11:3
        %36 = 9
        %15 = xor %36, %35
        %37 = %15
        jnz %37, @5_body, @7_exit
        ; (__main_entry)


      5_body:  ; IN=[4_condition] OUT=[4_condition] => {%11:4, %var8_0:3}
        %38 = %11:3
        %39 = %var8_0:2
        %22 = add %39, %38
        %41 = %22
        %40 = %var8_0:2
        %24 = gt %40, %41
        %42 = %24
        %25 = iszero %42
        %43 = %25
        assert %43
        %var8_0:3 = %22
        %44 = %11:3
        %45 = 1
        %11:4 = add %45, %44
        jmp @4_condition
        ; (__main_entry)


      7_exit:  ; IN=[4_condition] OUT=[] => {}
        %46 = %var8_0:2
        %47 = 64
        mstore %47, %46
        %48 = 32
        %49 = 64
        return %49, %48
        ; (__main_entry)


      fallback:  ; IN=[__main_entry] OUT=[] => {}
        %50 = 0
        %51 = 0
        revert %51, %50
        ; (__main_entry)
    }  ; close function __main_entry
    """
    ctx = parse_venom(source)

    expected_ctx = IRContext()
    expected_ctx.add_function(entry_fn := IRFunction(IRLabel("__main_entry")))

    expect_bb = IRBasicBlock(IRLabel("4_condition"), entry_fn)
    entry_fn.append_basic_block(expect_bb)

    expect_bb.append_instruction(
        "phi",
        IRLabel("1_then"),
        IRVariable("%var8_0"),
        IRLabel("5_body"),
        IRVariable("%var8_0:3"),
        ret=IRVariable("var8_0:2"),
    )
    expect_bb.append_instruction(
        "phi",
        IRLabel("1_then"),
        IRVariable("%11"),
        IRLabel("5_body"),
        IRVariable("%11:4"),
        ret=IRVariable("11:3"),
    )
    expect_bb.append_instruction("store", IRVariable("11:3"), ret=IRVariable("%35"))
    expect_bb.append_instruction("store", IRLiteral(9), ret=IRVariable("%36"))
    expect_bb.append_instruction("xor", IRVariable("%35"), IRVariable("%36"), ret=IRVariable("%15"))
    expect_bb.append_instruction("store", IRVariable("%15"), ret=IRVariable("%37"))
    expect_bb.append_instruction("jnz", IRVariable("%37"), IRLabel("5_body"), IRLabel("7_exit"))
    # other basic blocks omitted for brevity

    parsed_fn = next(iter(ctx.functions.values()))
    assert_bb_eq(parsed_fn.get_basic_block(expect_bb.label.name), expect_bb)

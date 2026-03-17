"""
Tests for VenomBuilder - the clean API for building Venom IR.
"""

from vyper.venom.basicblock import IRLabel
from vyper.venom.builder import VenomBuilder
from vyper.venom.context import IRContext


def test_builder_basic_arithmetic():
    """Test basic arithmetic operations."""
    ctx = IRContext()
    fn = ctx.create_function("test_func")
    b = VenomBuilder(ctx, fn)

    x = b.calldataload(4)
    y = b.calldataload(36)
    sum_val = b.add(x, y)
    diff = b.sub(x, y)
    prod = b.mul(sum_val, diff)
    b.mstore(prod, 0)
    b.return_(32, 0)

    # Verify basic structure
    assert fn.entry is not None
    assert fn.entry.is_terminated
    instrs = fn.entry.instructions
    assert len(instrs) == 7
    assert instrs[0].opcode == "calldataload"
    assert instrs[1].opcode == "calldataload"
    assert instrs[2].opcode == "add"
    assert instrs[3].opcode == "sub"
    assert instrs[4].opcode == "mul"
    assert instrs[5].opcode == "mstore"
    assert instrs[6].opcode == "return"


def test_builder_block_management():
    """Test block creation and switching."""
    ctx = IRContext()
    fn = ctx.create_function("test_blocks")
    b = VenomBuilder(ctx, fn)

    # Entry block
    cond = b.calldataload(0)

    # Create blocks without appending
    then_bb = b.create_block("then")
    else_bb = b.create_block("else")
    exit_bb = b.create_block("exit")

    # Branch
    b.jnz(cond, then_bb.label, else_bb.label)

    # Then block
    b.append_block(then_bb)
    b.set_block(then_bb)
    result_then = b.add(cond, 1)
    b.jmp(exit_bb.label)

    # Else block
    b.append_block(else_bb)
    b.set_block(else_bb)
    result_else = b.sub(cond, 1)
    b.jmp(exit_bb.label)

    # Exit block
    b.append_block(exit_bb)
    b.set_block(exit_bb)
    b.mstore(0, 0)
    b.return_(32, 0)

    # Verify structure
    assert fn.num_basic_blocks == 4
    assert fn.entry.is_terminated
    assert then_bb.is_terminated
    assert else_bb.is_terminated
    assert exit_bb.is_terminated


def test_builder_create_and_switch_block():
    """Test the convenience method create_and_switch_block."""
    ctx = IRContext()
    fn = ctx.create_function("test_convenience")
    b = VenomBuilder(ctx, fn)

    b.jmp(IRLabel("next", False))

    # Use convenience method
    next_bb = b.create_and_switch_block("next")

    assert b.current_block == next_bb
    assert fn.num_basic_blocks == 2


def test_builder_new_variable():
    """Test creating variables without emitting instructions."""
    ctx = IRContext()
    fn = ctx.create_function("test_var")
    b = VenomBuilder(ctx, fn)

    # Create variable before use
    result_var = b.new_variable()

    # Use it in assign_to
    x = b.calldataload(0)
    b.assign_to(x, result_var)
    b.stop()

    # Verify
    instrs = fn.entry.instructions
    assert len(instrs) == 3
    assert instrs[1].opcode == "assign"
    assert instrs[1].get_outputs()[0] == result_var


def test_builder_invoke():
    """Test internal function calls."""
    ctx = IRContext()
    fn = ctx.create_function("test_invoke")
    callee = ctx.create_function("callee")
    b = VenomBuilder(ctx, fn)

    x = b.calldataload(0)
    results = b.invoke(callee.name, [x], returns=2)
    b.mstore(results[0], 0)
    b.mstore(results[1], 32)
    b.return_(64, 0)

    # Verify
    assert len(results) == 2
    instrs = fn.entry.instructions
    invoke_instr = instrs[1]
    assert invoke_instr.opcode == "invoke"
    assert invoke_instr.num_outputs == 2


def test_builder_storage_ops():
    """Test storage operations."""
    ctx = IRContext()
    fn = ctx.create_function("test_storage")
    b = VenomBuilder(ctx, fn)

    slot = b.calldataload(0)
    val = b.sload(slot)
    new_val = b.add(val, 1)
    b.sstore(new_val, slot)
    b.stop()

    instrs = fn.entry.instructions
    assert instrs[1].opcode == "sload"
    assert instrs[3].opcode == "sstore"


def test_builder_comparison_ops():
    """Test comparison operations."""
    ctx = IRContext()
    fn = ctx.create_function("test_cmp")
    b = VenomBuilder(ctx, fn)

    x = b.calldataload(0)
    y = b.calldataload(32)

    eq_result = b.eq(x, y)
    lt_result = b.lt(x, y)
    gt_result = b.gt(x, y)
    is_zero = b.iszero(x)
    b.stop()

    instrs = fn.entry.instructions
    assert instrs[2].opcode == "eq"
    assert instrs[3].opcode == "lt"
    assert instrs[4].opcode == "gt"
    assert instrs[5].opcode == "iszero"


def test_builder_bitwise_ops():
    """Test bitwise operations."""
    ctx = IRContext()
    fn = ctx.create_function("test_bitwise")
    b = VenomBuilder(ctx, fn)

    x = b.calldataload(0)
    y = b.calldataload(32)

    and_result = b.and_(x, y)
    or_result = b.or_(x, y)
    xor_result = b.xor(x, y)
    not_result = b.not_(x)
    shl_result = b.shl(8, x)
    shr_result = b.shr(8, x)
    b.stop()

    instrs = fn.entry.instructions
    assert instrs[2].opcode == "and"
    assert instrs[3].opcode == "or"
    assert instrs[4].opcode == "xor"
    assert instrs[5].opcode == "not"
    assert instrs[6].opcode == "shl"
    assert instrs[7].opcode == "shr"


def test_builder_environment_ops():
    """Test environment operations."""
    ctx = IRContext()
    fn = ctx.create_function("test_env")
    b = VenomBuilder(ctx, fn)

    caller = b.caller()
    value = b.callvalue()
    size = b.calldatasize()
    addr = b.address()
    bal = b.selfbalance()
    b.stop()

    instrs = fn.entry.instructions
    assert instrs[0].opcode == "caller"
    assert instrs[1].opcode == "callvalue"
    assert instrs[2].opcode == "calldatasize"
    assert instrs[3].opcode == "address"
    assert instrs[4].opcode == "selfbalance"


def test_builder_block_info():
    """Test block info operations."""
    ctx = IRContext()
    fn = ctx.create_function("test_block_info")
    b = VenomBuilder(ctx, fn)

    ts = b.timestamp()
    num = b.number()
    cb = b.coinbase()
    rand = b.prevrandao()
    limit = b.gaslimit()
    chain = b.chainid()
    b.stop()

    instrs = fn.entry.instructions
    assert instrs[0].opcode == "timestamp"
    assert instrs[1].opcode == "number"
    assert instrs[2].opcode == "coinbase"
    assert instrs[3].opcode == "prevrandao"
    assert instrs[4].opcode == "gaslimit"
    assert instrs[5].opcode == "chainid"


def test_builder_is_terminated():
    """Test is_terminated check."""
    ctx = IRContext()
    fn = ctx.create_function("test_term")
    b = VenomBuilder(ctx, fn)

    assert not b.is_terminated()
    b.stop()
    assert b.is_terminated()


def test_builder_literal_helper():
    """Test literal helper method."""
    ctx = IRContext()
    fn = ctx.create_function("test_literal")
    b = VenomBuilder(ctx, fn)

    lit = b.literal(42)
    assert lit.value == 42


def test_builder_label_helper():
    """Test label helper method."""
    ctx = IRContext()
    fn = ctx.create_function("test_label")
    b = VenomBuilder(ctx, fn)

    lbl = b.label("my_label", is_symbol=True)
    assert lbl.value == "my_label"
    assert lbl.is_symbol is True


def test_builder_current_block_property():
    """Test current_block property."""
    ctx = IRContext()
    fn = ctx.create_function("test_current")
    b = VenomBuilder(ctx, fn)

    assert b.current_block == fn.entry

    new_bb = b.create_block("new")
    b.append_block(new_bb)
    b.set_block(new_bb)

    assert b.current_block == new_bb


def test_builder_crypto_ops():
    """Test crypto operations."""
    ctx = IRContext()
    fn = ctx.create_function("test_crypto")
    b = VenomBuilder(ctx, fn)

    ptr = b.calldataload(0)
    size = b.calldataload(32)
    hash_result = b.sha3(ptr, size)

    a = b.calldataload(64)
    b_val = b.calldataload(96)
    hash_64 = b.sha3_64(a, b_val)
    b.stop()

    instrs = fn.entry.instructions
    assert instrs[2].opcode == "sha3"
    assert instrs[5].opcode == "sha3_64"

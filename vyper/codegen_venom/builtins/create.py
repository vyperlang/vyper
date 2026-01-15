"""
Contract creation built-in functions for Venom IR.

- raw_create(bytecode, *ctor_args, value=0, salt=None, revert_on_failure=True)
- create_minimal_proxy_to(target, value=0, salt=None, revert_on_failure=True)
- create_copy_of(target, value=0, salt=None, revert_on_failure=True)
- create_from_blueprint(target, *ctor_args, value=0, salt=None, raw_args=False,
                        code_offset=3, revert_on_failure=True)
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from vyper import ast as vy_ast
from vyper.codegen_venom.abi import abi_encode_to_buf
from vyper.exceptions import CompilerPanic, UnfoldableNode
from vyper.ir.compile_ir import assembly_to_evm
from vyper.semantics.data_locations import DataLocation
from vyper.semantics.types import TupleT
from vyper.utils import bytes_to_int
from vyper.venom.basicblock import IRLiteral, IROperand

if TYPE_CHECKING:
    from vyper.codegen_venom.context import VenomCodegenContext


def _get_kwarg_value(node: vy_ast.Call, kwarg_name: str, default=None):
    """Extract a keyword argument value from a Call node."""
    for kw in node.keywords:
        if kw.arg == kwarg_name:
            return kw.value
    return default


def _get_literal_kwarg(node: vy_ast.Call, kwarg_name: str, default):
    """Extract a literal value from a keyword argument.

    Returns (value, is_literal) tuple. If is_literal is False, the value is None
    and the caller should evaluate the kwarg at runtime.
    """
    kw_node = _get_kwarg_value(node, kwarg_name)
    if kw_node is None:
        return default, True
    # Try to get folded value
    try:
        folded = kw_node.get_folded_value()
        if isinstance(folded, vy_ast.Int):
            return folded.value, True
        if isinstance(folded, vy_ast.NameConstant):
            return folded.value, True
    except (KeyError, UnfoldableNode):
        # Not foldable - caller needs to evaluate at runtime
        pass
    # Try direct value
    if isinstance(kw_node, vy_ast.Int):
        return kw_node.value, True
    if isinstance(kw_node, vy_ast.NameConstant):
        return kw_node.value, True
    return None, False


def _has_kwarg(node: vy_ast.Call, kwarg_name: str) -> bool:
    """Check if a keyword argument is present."""
    return any(kw.arg == kwarg_name for kw in node.keywords)


def _check_create_result(b, addr: IROperand, revert_on_failure: bool) -> IROperand:
    """Optionally check CREATE/CREATE2 result and revert on failure.

    CREATE/CREATE2 return 0 on failure (out of gas or constructor reverts).
    If revert_on_failure is True, we check addr != 0 and bubble up revert data.
    """
    if revert_on_failure:
        # Check if creation succeeded (addr != 0)
        # If failed, copy and propagate revert data from the failed constructor
        fail_bb = b.create_block("create_fail")
        b.append_block(fail_bb)
        exit_bb = b.create_block("create_ok")
        b.append_block(exit_bb)

        # jnz: if addr != 0, jump to exit (success), else fall through to fail
        b.jnz(addr, exit_bb.label, fail_bb.label)

        # Failure path: bubble up revert data
        b.set_block(fail_bb)
        revert_size = b.returndatasize()
        b.returndatacopy(IRLiteral(0), IRLiteral(0), revert_size)
        b.revert(IRLiteral(0), revert_size)

        # Success path
        b.set_block(exit_bb)
    return addr


# EIP-1167 bytecode components
def _eip1167_bytecode():
    """Generate EIP-1167 minimal proxy bytecode components.

    Returns (loader_evm, forwarder_pre_evm, forwarder_post_evm) as bytes.
    The complete proxy is: loader + forwarder_pre + <20-byte target> + forwarder_post
    """
    loader_asm = [
        "PUSH1",
        0x2D,  # Total runtime size (45 bytes)
        "RETURNDATASIZE",
        "DUP2",
        "PUSH1",
        0x09,  # Loader size (9 bytes)
        "RETURNDATASIZE",
        "CODECOPY",
        "RETURN",
    ]
    forwarder_pre_asm = [
        "CALLDATASIZE",
        "RETURNDATASIZE",
        "RETURNDATASIZE",
        "CALLDATACOPY",
        "RETURNDATASIZE",
        "RETURNDATASIZE",
        "RETURNDATASIZE",
        "CALLDATASIZE",
        "RETURNDATASIZE",
        "PUSH20",  # <address to delegate to follows>
    ]
    forwarder_post_asm = [
        "GAS",
        "DELEGATECALL",
        "RETURNDATASIZE",
        "DUP3",
        "DUP1",
        "RETURNDATACOPY",
        "SWAP1",
        "RETURNDATASIZE",
        "SWAP2",
        "PUSH1",
        0x2B,  # Jumpdest location
        "JUMPI",
        "REVERT",
        "JUMPDEST",
        "RETURN",
    ]
    return (
        assembly_to_evm(loader_asm)[0],
        assembly_to_evm(forwarder_pre_asm)[0],
        assembly_to_evm(forwarder_post_asm)[0],
    )


def _create_preamble_bytes():
    """Generate 11-byte preamble for initcode that returns code at offset 0x0b.

    Returns the raw EVM bytecode (11 bytes) with codesize placeholder.
    The codesize (3 bytes) will be OR'd in at runtime for PUSH3.
    """
    evm_len = 0x0B  # 11 bytes
    asm = [
        # PUSH3 allows codesize up to 2^24-1 bytes
        "PUSH3",
        0x00,  # placeholder for codesize byte 1
        0x00,  # placeholder for codesize byte 2
        0x00,  # placeholder for codesize byte 3
        "RETURNDATASIZE",  # Push 0 (memory dest)
        "DUP2",  # Copy codesize
        "PUSH1",
        evm_len,  # Code starts at offset 11
        "RETURNDATASIZE",  # Push 0 (code offset in calldata)
        "CODECOPY",  # Copy code to memory
        "RETURN",  # Return the code
    ]
    evm = assembly_to_evm(asm)[0]
    assert len(evm) == evm_len, f"Preamble length mismatch: {len(evm)} != {evm_len}"
    return evm


def lower_raw_create(node: vy_ast.Call, ctx: VenomCodegenContext) -> IROperand:
    """
    raw_create(bytecode, *ctor_args, value=0, salt=None, revert_on_failure=True)

    Deploy contract from raw bytecode with optional constructor arguments.
    Constructor args are ABI-encoded and appended to bytecode.

    Returns deployed contract address.
    """
    from vyper.codegen_venom.expr import Expr

    ctx.check_is_not_constant("use raw_create", node)

    b = ctx.builder

    # Parse positional args: bytecode is first, rest are ctor_args
    bytecode_node = node.args[0]
    ctor_arg_nodes = node.args[1:]

    # Get bytecode - may be in memory, storage, or transient
    bytecode_vv = Expr(bytecode_node, ctx).lower()
    bytecode_typ = bytecode_node._metadata["type"]

    # Ensure bytecode is in memory. Storage/transient data needs to be copied first.
    # This is critical when ctor args might modify the storage location that holds
    # the bytecode (cf. test_raw_create_change_initcode_size).
    if bytecode_vv.location in (DataLocation.STORAGE, DataLocation.TRANSIENT):
        # Allocate memory buffer and copy from storage/transient
        mem_buf = ctx.new_temporary_value(bytecode_typ)
        ctx.slot_to_memory(
            bytecode_vv.operand,
            mem_buf.operand,
            bytecode_typ.storage_size_in_words,
            bytecode_vv.location,
        )
        bytecode = mem_buf.operand
    else:
        # Memory bytecode: copy to fresh buffer to avoid potential overlap
        # when evaluating value, salt, or ctor_args expressions
        # (cf. test_raw_create_memory_overlap - e.g. value=arr.pop())
        mem_buf = ctx.new_temporary_value(bytecode_typ)
        bytecode_len_tmp = b.mload(bytecode_vv.operand)
        # Copy length word + data
        copy_size = b.add(bytecode_len_tmp, IRLiteral(32))
        ctx.copy_memory_dynamic(mem_buf.operand, bytecode_vv.operand, copy_size)
        bytecode = mem_buf.operand

    # Parse kwargs
    value_node = _get_kwarg_value(node, "value")
    salt_node = _get_kwarg_value(node, "salt")
    revert_on_failure, _ = _get_literal_kwarg(node, "revert_on_failure", True)

    if value_node is not None:
        value = Expr(value_node, ctx).lower_value()
    else:
        value = IRLiteral(0)

    # Get bytecode length and data pointer
    bytecode_len = b.mload(bytecode)
    bytecode_ptr = b.add(bytecode, IRLiteral(32))

    # If no constructor args, just create with bytecode
    if len(ctor_arg_nodes) == 0:
        if salt_node is not None:
            salt = Expr(salt_node, ctx).lower_value()
            addr = b.create2(value, bytecode_ptr, bytecode_len, salt)
        else:
            addr = b.create(value, bytecode_ptr, bytecode_len)
        return _check_create_result(b, addr, revert_on_failure)

    # With ctor args: need to ABI-encode and append to bytecode
    # Create tuple type for encoding
    ctor_arg_types = [arg._metadata["type"] for arg in ctor_arg_nodes]
    ctor_tuple_typ = TupleT(tuple(ctor_arg_types))
    ctor_abi_size = ctor_tuple_typ.abi_type.size_bound()

    # Calculate buffer size: max bytecode len + ctor args size
    buf_size = bytecode_typ.maxlen + ctor_abi_size
    buf = ctx.allocate_buffer(buf_size, annotation="raw_create_buf")

    # Copy bytecode to buffer
    ctx.copy_memory_dynamic(buf._ptr, bytecode_ptr, bytecode_len)

    # Encode ctor args after bytecode
    # First, store ctor args to a temp buffer
    ctor_arg_values = [Expr(arg, ctx).lower_value() for arg in ctor_arg_nodes]
    ctor_args_val = ctx.new_temporary_value(ctor_tuple_typ)
    offset = 0
    for val, arg_t in zip(ctor_arg_values, ctor_arg_types):
        if offset == 0:
            dst = ctor_args_val.operand
        else:
            dst = b.add(ctor_args_val.operand, IRLiteral(offset))
        ctx.store_memory(val, dst, arg_t)
        offset += arg_t.memory_bytes_required

    # Now ABI encode from ctor_args_val to args_start
    args_start = b.add(buf._ptr, bytecode_len)
    args_len = abi_encode_to_buf(ctx, args_start, ctor_args_val.operand, ctor_tuple_typ)

    # Total length = bytecode_len + args_len
    total_len = b.add(bytecode_len, args_len)

    # Create contract
    if salt_node is not None:
        salt = Expr(salt_node, ctx).lower_value()
        addr = b.create2(value, buf._ptr, total_len, salt)
    else:
        addr = b.create(value, buf._ptr, total_len)

    return _check_create_result(b, addr, revert_on_failure)


def lower_create_minimal_proxy_to(node: vy_ast.Call, ctx: VenomCodegenContext) -> IROperand:
    """
    create_minimal_proxy_to(target, value=0, salt=None, revert_on_failure=True)

    Create an EIP-1167 minimal proxy pointing to target contract.
    The proxy delegates all calls to target.

    Returns deployed proxy address.
    """
    from vyper.codegen_venom.expr import Expr

    ctx.check_is_not_constant("use create_minimal_proxy_to", node)

    b = ctx.builder

    # Parse args
    target = Expr(node.args[0], ctx).lower_value()

    # Parse kwargs
    value_node = _get_kwarg_value(node, "value")
    salt_node = _get_kwarg_value(node, "salt")
    revert_on_failure, _ = _get_literal_kwarg(node, "revert_on_failure", True)

    if value_node is not None:
        value = Expr(value_node, ctx).lower_value()
    else:
        value = IRLiteral(0)

    # Get EIP-1167 bytecode components
    loader_evm, forwarder_pre_evm, forwarder_post_evm = _eip1167_bytecode()

    # Calculate sizes and offsets
    # loader: 9 bytes, forwarder_pre: 10 bytes (including PUSH20), forwarder_post: 15 bytes
    # Total: 9 + 10 + 20 (address) + 15 = 54 bytes
    preamble_length = len(loader_evm) + len(forwarder_pre_evm)  # 9 + 10 = 19
    buf_len = preamble_length + 20 + len(forwarder_post_evm)  # 19 + 20 + 15 = 54 bytes total

    # Allocate 96-byte buffer (to fit 3 x 32-byte stores)
    buf = ctx.allocate_buffer(96, annotation="proxy_buf")

    # Build the preamble as a 32-byte value (left-aligned)
    forwarder_preamble = bytes_to_int(
        loader_evm + forwarder_pre_evm + b"\x00" * (32 - preamble_length)
    )

    # Build post as a 32-byte value (left-aligned)
    forwarder_post = bytes_to_int(forwarder_post_evm + b"\x00" * (32 - len(forwarder_post_evm)))

    # Store preamble at buf
    b.mstore(buf._ptr, IRLiteral(forwarder_preamble))

    # Left-align target address (shift left by 96 bits = 12 bytes)
    aligned_target = b.shl(IRLiteral(96), target)

    # Store target at buf + preamble_length
    target_offset = b.add(buf._ptr, IRLiteral(preamble_length))
    b.mstore(target_offset, aligned_target)

    # Store post at buf + preamble_length + 20
    post_offset = b.add(buf._ptr, IRLiteral(preamble_length + 20))
    b.mstore(post_offset, IRLiteral(forwarder_post))

    # Create contract
    if salt_node is not None:
        salt = Expr(salt_node, ctx).lower_value()
        addr = b.create2(value, buf._ptr, IRLiteral(buf_len), salt)
    else:
        addr = b.create(value, buf._ptr, IRLiteral(buf_len))

    return _check_create_result(b, addr, revert_on_failure)


def lower_create_copy_of(node: vy_ast.Call, ctx: VenomCodegenContext) -> IROperand:
    """
    create_copy_of(target, value=0, salt=None, revert_on_failure=True)

    Deploy a copy of target contract's runtime bytecode.
    Creates initcode that copies target's code and returns it.

    Returns deployed contract address.
    """
    from vyper.codegen_venom.expr import Expr

    ctx.check_is_not_constant("use create_copy_of", node)

    b = ctx.builder

    # Parse args
    target = Expr(node.args[0], ctx).lower_value()

    # Parse kwargs
    value_node = _get_kwarg_value(node, "value")
    salt_node = _get_kwarg_value(node, "salt")
    revert_on_failure, _ = _get_literal_kwarg(node, "revert_on_failure", True)

    if value_node is not None:
        value = Expr(value_node, ctx).lower_value()
    else:
        value = IRLiteral(0)

    # Evaluate salt BEFORE msize() to ensure any memory allocations
    # (e.g., from keccak256(_abi_encode(x))) don't overwrite the initcode buffer
    salt: Optional[IROperand] = None
    if salt_node is not None:
        salt = Expr(salt_node, ctx).lower_value()

    # Get target code size
    codesize = b.extcodesize(target)

    # Assert target has code (codesize > 0)
    b.assert_(codesize)

    # Generate preamble bytecode (11 bytes)
    preamble_bytes = _create_preamble_bytes()
    preamble_len = len(preamble_bytes)  # 11
    preamble_base = bytes_to_int(preamble_bytes)

    # The codesize goes at bits [7*8 : 4*8] in the preamble (after PUSH3, before rest)
    # Actually, codesize needs to be shifted left by (preamble_len - 4) * 8 = 7*8 = 56 bits
    # to place it right after the PUSH3 opcode
    shl_bits = (preamble_len - 4) * 8  # 56 bits

    # Combine preamble_base with shifted codesize
    shifted_codesize = b.shl(IRLiteral(shl_bits), codesize)
    preamble_with_size = b.or_(IRLiteral(preamble_base), shifted_codesize)

    # Get current memory size as buffer start
    mem_ofst = b.msize()

    # Store preamble at mem_ofst (will be stored as 32-byte word)
    b.mstore(mem_ofst, preamble_with_size)

    # Copy target code after the preamble
    # Memory layout: [32-byte word with 11-byte preamble at end] [target code]
    # The preamble is right-aligned in the 32-byte word, so code starts at mem_ofst + 32
    code_dest = b.add(mem_ofst, IRLiteral(32))
    b.extcodecopy(target, code_dest, IRLiteral(0), codesize)

    # Buffer starts at mem_ofst + (32 - preamble_len) = mem_ofst + 21
    buf = b.add(mem_ofst, IRLiteral(32 - preamble_len))

    # Total length = preamble_len + codesize
    buf_len = b.add(codesize, IRLiteral(preamble_len))

    # Create contract
    if salt is not None:
        addr = b.create2(value, buf, buf_len, salt)
    else:
        addr = b.create(value, buf, buf_len)

    return _check_create_result(b, addr, revert_on_failure)


def lower_create_from_blueprint(node: vy_ast.Call, ctx: VenomCodegenContext) -> IROperand:
    """
    create_from_blueprint(target, *ctor_args, value=0, salt=None,
                          raw_args=False, code_offset=3, revert_on_failure=True)

    Deploy from a blueprint contract (EIP-5202 style).
    The blueprint stores initcode prefixed by a code_offset-byte preamble.
    Constructor args are ABI-encoded (or passed raw if raw_args=True) and
    appended to the initcode.

    Returns deployed contract address.
    """
    from vyper.codegen_venom.expr import Expr

    ctx.check_is_not_constant("use create_from_blueprint", node)

    b = ctx.builder

    # Parse args: target is first, rest are ctor_args
    target = Expr(node.args[0], ctx).lower_value()
    ctor_arg_nodes = node.args[1:]

    # Parse kwargs
    value_node = _get_kwarg_value(node, "value")
    salt_node = _get_kwarg_value(node, "salt")
    code_offset_node = _get_kwarg_value(node, "code_offset")
    code_offset_lit, code_offset_is_literal = _get_literal_kwarg(node, "code_offset", 3)
    raw_args, _ = _get_literal_kwarg(node, "raw_args", False)
    revert_on_failure, _ = _get_literal_kwarg(node, "revert_on_failure", True)

    if value_node is not None:
        value = Expr(value_node, ctx).lower_value()
    else:
        value = IRLiteral(0)

    # Evaluate salt BEFORE msize() to ensure any memory allocations
    # (e.g., from keccak256(_abi_encode(x))) don't overwrite the initcode
    salt: Optional[IROperand] = None
    if salt_node is not None:
        salt = Expr(salt_node, ctx).lower_value()

    # Get code_offset as IROperand (literal or runtime value)
    code_offset: IROperand
    if code_offset_is_literal:
        code_offset = IRLiteral(code_offset_lit)
    else:
        assert code_offset_node is not None
        code_offset = Expr(code_offset_node, ctx).lower_value()

    # Get blueprint code size (minus preamble)
    full_codesize = b.extcodesize(target)
    codesize = b.sub(full_codesize, code_offset)

    # Assert blueprint has code after preamble (codesize > 0)
    # Use sgt since codesize could underflow if code_offset > extcodesize
    has_code = b.sgt(codesize, IRLiteral(0))
    b.assert_(has_code)

    # Handle constructor arguments
    # NOTE: ALL memory allocations (including ABI encoding) MUST happen BEFORE
    # calling msize(). This ensures msize() returns a value past all alloca buffers.
    args_len: IROperand
    args_ptr: IROperand

    if raw_args:
        # raw_args=True: single bytes argument contains raw constructor args
        if len(ctor_arg_nodes) != 1:
            # This should be caught by type checker, but be defensive
            raise CompilerPanic("raw_args requires exactly 1 bytes argument")

        raw_arg_vv = Expr(ctor_arg_nodes[0], ctx).lower()
        raw_arg = ctx.unwrap(raw_arg_vv)  # Copies storage/transient to memory
        args_len = b.mload(raw_arg)
        args_ptr = b.add(raw_arg, IRLiteral(32))
    elif len(ctor_arg_nodes) > 0:
        # ABI-encode constructor arguments BEFORE calling msize()
        # This ensures all alloca buffers are written to before msize() is evaluated
        ctor_arg_types = [arg._metadata["type"] for arg in ctor_arg_nodes]
        ctor_tuple_typ = TupleT(tuple(ctor_arg_types))
        ctor_abi_size = ctor_tuple_typ.abi_type.size_bound()

        # Allocate buffer for encoded args
        args_buf = ctx.allocate_buffer(ctor_abi_size, annotation="ctor_args_buf")

        # Evaluate and store ctor args to temp buffer
        ctor_arg_values = [Expr(arg, ctx).lower_value() for arg in ctor_arg_nodes]
        ctor_args_src = ctx.new_temporary_value(ctor_tuple_typ)
        offset = 0
        for val, arg_t in zip(ctor_arg_values, ctor_arg_types):
            if offset == 0:
                dst = ctor_args_src.operand
            else:
                dst = b.add(ctor_args_src.operand, IRLiteral(offset))
            ctx.store_memory(val, dst, arg_t)
            offset += arg_t.memory_bytes_required

        # ABI encode from ctor_args_src to args_buf (BEFORE msize!)
        args_len = abi_encode_to_buf(ctx, args_buf._ptr, ctor_args_src.operand, ctor_tuple_typ)
        args_ptr = args_buf._ptr
    else:
        # No constructor arguments
        args_len = IRLiteral(0)
        args_ptr = IRLiteral(0)

    # Get current memory size as buffer start
    # This is called AFTER all memory allocations to ensure msize() is past all alloca buffers
    mem_ofst = b.msize()

    # Copy blueprint code (skipping preamble) to memory
    b.extcodecopy(target, mem_ofst, code_offset, codesize)

    # Append constructor args after code (copy from pre-encoded buffer)
    if not isinstance(args_len, IRLiteral) or args_len.value > 0:
        args_dest = b.add(mem_ofst, codesize)
        ctx.copy_memory_dynamic(args_dest, args_ptr, args_len)

    # Total length = codesize + args_len
    if isinstance(args_len, IRLiteral) and args_len.value == 0:
        total_len = codesize
    else:
        total_len = b.add(codesize, args_len)

    # Create contract
    if salt is not None:
        addr = b.create2(value, mem_ofst, total_len, salt)
    else:
        addr = b.create(value, mem_ofst, total_len)

    return _check_create_result(b, addr, revert_on_failure)


HANDLERS = {
    "raw_create": lower_raw_create,
    "create_minimal_proxy_to": lower_create_minimal_proxy_to,
    "create_forwarder_to": lower_create_minimal_proxy_to,  # deprecated alias
    "create_copy_of": lower_create_copy_of,
    "create_from_blueprint": lower_create_from_blueprint,
}

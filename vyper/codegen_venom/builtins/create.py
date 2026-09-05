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
from vyper.codegen_venom.abi import abi_encode_values_to_buf, runtime_abi_size_for_encode
from vyper.codegen_venom.builtins._call import BuiltinCall
from vyper.ir.compile_ir import assembly_to_evm
from vyper.semantics.types import (
    TupleT,
    is_unbounded_bytestring_type,
    type_contains_unbounded_sequence,
)
from vyper.utils import EIP_3860_LIMIT, bytes_to_int
from vyper.venom.basicblock import IRLiteral, IROperand, IRVariable

if TYPE_CHECKING:
    from vyper.codegen_venom.context import VenomCodegenContext


def _check_create_result(
    ctx: VenomCodegenContext, b, addr: IROperand, revert_on_failure: bool
) -> IROperand:
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
        revert_buffer = ctx.allocate_buffer(0, annotation="create revert on failure buffer")
        b.returndatacopy(revert_buffer._ptr, IRLiteral(0), revert_size)
        b.revert(revert_buffer._ptr, revert_size)

        # Success path
        b.set_block(exit_bb)
    return addr


def _emit_create(
    ctx: VenomCodegenContext,
    b,
    value: IROperand,
    initcode: IROperand,
    initcode_len: IROperand,
    salt: Optional[IROperand],
    revert_on_failure: bool,
    check_eip_3860_limit: bool = True,
) -> IROperand:
    """Emit CREATE/CREATE2, optionally guarding the EIP-3860 initcode limit.

    Oversized initcode is an exceptional abort at CREATE, not a zero return,
    so with revert_on_failure=False the guard skips CREATE and yields the
    zero address; otherwise it reverts cleanly before CREATE.
    """
    if not check_eip_3860_limit:
        if salt is not None:
            addr = b.create2(value, initcode, initcode_len, salt)
        else:
            addr = b.create(value, initcode, initcode_len)
        return _check_create_result(ctx, b, addr, revert_on_failure)

    in_eip_3860_limit = b.iszero(b.gt(initcode_len, IRLiteral(EIP_3860_LIMIT)))

    if revert_on_failure:
        b.assert_(in_eip_3860_limit)
        if salt is not None:
            addr = b.create2(value, initcode, initcode_len, salt)
        else:
            addr = b.create(value, initcode, initcode_len)
        return _check_create_result(ctx, b, addr, revert_on_failure)

    ret_cell = ctx.allocate_buffer(32, annotation="create_result")
    create_bb = b.create_block("create")
    oversize_bb = b.create_block("create_oversize")
    exit_bb = b.create_block("create_exit")

    b.jnz(in_eip_3860_limit, create_bb.label, oversize_bb.label)

    b.append_block(create_bb)
    b.set_block(create_bb)
    if salt is not None:
        addr = b.create2(value, initcode, initcode_len, salt)
    else:
        addr = b.create(value, initcode, initcode_len)
    b.mstore(ret_cell._ptr, addr)
    b.jmp(exit_bb.label)

    b.append_block(oversize_bb)
    b.set_block(oversize_bb)
    b.mstore(ret_cell._ptr, IRLiteral(0))
    b.jmp(exit_bb.label)

    b.append_block(exit_bb)
    b.set_block(exit_bb)
    return b.mload(ret_cell._ptr)


def _ctor_args_need_runtime_encoding(ctor_arg_types) -> bool:
    return any(type_contains_unbounded_sequence(t) for t in ctor_arg_types)


def _prepare_ctor_args(call: BuiltinCall, ctor_arg_nodes: list[vy_ast.VyperNode]):
    ctx = call.ctx

    ctor_arg_types = [arg._metadata["type"] for arg in ctor_arg_nodes]
    ctor_tuple_typ = TupleT(tuple(ctor_arg_types))
    runtime_ctor_args = _ctor_args_need_runtime_encoding(ctor_arg_types)
    ctor_arg_vvs = [call.value(arg) for arg in ctor_arg_nodes]

    if runtime_ctor_args:
        ctor_abi_size = runtime_abi_size_for_encode(ctx, ctor_arg_vvs, ctor_tuple_typ)
    else:
        ctor_abi_size = IRLiteral(ctor_tuple_typ.abi_type.size_bound())

    return ctor_tuple_typ, ctor_arg_vvs, runtime_ctor_args, ctor_abi_size


def _encode_ctor_args_to_buf(
    ctx: VenomCodegenContext, dst: IRVariable, ctor_tuple_typ: TupleT, ctor_arg_vvs
) -> IROperand:
    return abi_encode_values_to_buf(ctx, dst, ctor_arg_vvs, ctor_tuple_typ)


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


def lower_raw_create(call: BuiltinCall) -> IROperand:
    """
    raw_create(bytecode, *ctor_args, value=0, salt=None, revert_on_failure=True)

    Deploy contract from raw bytecode with optional constructor arguments.
    Constructor args are ABI-encoded and appended to bytecode.

    Returns deployed contract address.
    """
    node = call.node
    ctx = call.ctx

    ctx.check_is_not_constant("use raw_create", node)

    b = ctx.builder

    # Parse positional args: bytecode is first, rest are ctor_args
    bytecode_node = node.args[0]
    ctor_arg_nodes = node.args[1:]

    # The preparation boundary has already stabilized the initcode.
    bytecode_vv = call.value(bytecode_node)
    bytecode_typ = bytecode_node._metadata["type"]

    bytecode_is_unbounded = is_unbounded_bytestring_type(bytecode_typ)

    bytecode = bytecode_vv.operand

    # Parse kwargs
    revert_on_failure = call.literal("revert_on_failure")

    # Get bytecode length and data pointer
    assert isinstance(bytecode, IRVariable)
    bytecode_len = b.mload(bytecode)
    bytecode_ptr = b.add(bytecode, IRLiteral(32))

    # If no constructor args, just create with bytecode
    if len(ctor_arg_nodes) == 0:
        value = call.kwarg("value")

        raw_salt_op: Optional[IROperand] = None
        if call.was_provided("salt"):
            raw_salt_op = call.kwarg("salt")
        check_eip_3860_limit = bytecode_is_unbounded
        return _emit_create(
            ctx,
            b,
            value,
            bytecode_ptr,
            bytecode_len,
            raw_salt_op,
            revert_on_failure,
            check_eip_3860_limit,
        )

    # With ctor args: need to ABI-encode and append to bytecode
    ctor_tuple_typ, ctor_arg_vvs, runtime_ctor_args, ctor_abi_size = _prepare_ctor_args(
        call, ctor_arg_nodes
    )

    # Calculate buffer size: max bytecode len + ctor args size for bounded
    # bytecode, or exact runtime bytecode length + ctor args size for INF.
    runtime_initcode = bytecode_is_unbounded or runtime_ctor_args

    if runtime_initcode:
        buf_ptr = ctx.allocate_scratch(ctx.checked_add(bytecode_len, ctor_abi_size))
    else:
        assert isinstance(ctor_abi_size, IRLiteral)
        buf_size = bytecode_typ.maxlen + ctor_abi_size.value
        buf = ctx.allocate_buffer(buf_size, annotation="raw_create_buf")
        buf_ptr = buf._ptr

    # Copy bytecode to buffer
    bytecode_max_len = None if bytecode_is_unbounded else bytecode_typ.maxlen
    ctx.copy_memory_dynamic(buf_ptr, bytecode_ptr, bytecode_len, bytecode_max_len)

    # Encode ctor args after bytecode
    args_start = b.add(buf_ptr, bytecode_len)
    args_len = _encode_ctor_args_to_buf(ctx, args_start, ctor_tuple_typ, ctor_arg_vvs)

    # Total length = bytecode_len + args_len
    if runtime_initcode:
        total_len = ctx.checked_add(bytecode_len, args_len)
    else:
        total_len = b.add(bytecode_len, args_len)

    # Create contract
    value = call.kwarg("value")

    ctor_salt_op: Optional[IROperand] = None
    if call.was_provided("salt"):
        ctor_salt_op = call.kwarg("salt")
    check_eip_3860_limit = runtime_initcode
    return _emit_create(
        ctx, b, value, buf_ptr, total_len, ctor_salt_op, revert_on_failure, check_eip_3860_limit
    )


def lower_create_minimal_proxy_to(call: BuiltinCall) -> IROperand:
    """
    create_minimal_proxy_to(target, value=0, salt=None, revert_on_failure=True)

    Create an EIP-1167 minimal proxy pointing to target contract.
    The proxy delegates all calls to target.

    Returns deployed proxy address.
    """
    node = call.node
    ctx = call.ctx

    ctx.check_is_not_constant("use create_minimal_proxy_to", node)

    b = ctx.builder

    # Parse args
    target = call.operand(node.args[0])

    # Parse kwargs
    revert_on_failure = call.literal("revert_on_failure")

    value = call.kwarg("value")

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
    if call.was_provided("salt"):
        salt = call.kwarg("salt")
        addr = b.create2(value, buf._ptr, IRLiteral(buf_len), salt)
    else:
        addr = b.create(value, buf._ptr, IRLiteral(buf_len))

    return _check_create_result(ctx, b, addr, revert_on_failure)


def lower_create_copy_of(call: BuiltinCall) -> IROperand:
    """
    create_copy_of(target, value=0, salt=None, revert_on_failure=True)

    Deploy a copy of target contract's runtime bytecode.
    Creates initcode that copies target's code and returns it.

    Returns deployed contract address.
    """
    node = call.node
    ctx = call.ctx

    ctx.check_is_not_constant("use create_copy_of", node)

    b = ctx.builder

    # Parse args
    target = call.operand(node.args[0])

    # Parse kwargs
    revert_on_failure = call.literal("revert_on_failure")

    value = call.kwarg("value")

    salt: Optional[IROperand] = None
    if call.was_provided("salt"):
        salt = call.kwarg("salt")

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

    # Scratch region holds: [32-byte preamble word] [codesize bytes of target code].
    scratch_size = b.add(codesize, IRLiteral(32))
    mem_ofst = ctx.allocate_scratch(scratch_size)

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

    return _check_create_result(ctx, b, addr, revert_on_failure)


def lower_create_from_blueprint(call: BuiltinCall) -> IROperand:
    """
    create_from_blueprint(target, *ctor_args, value=0, salt=None,
                          raw_args=False, code_offset=3, revert_on_failure=True)

    Deploy from a blueprint contract (EIP-5202 style).
    The blueprint stores initcode prefixed by a code_offset-byte preamble.
    Constructor args are ABI-encoded (or passed raw if raw_args=True) and
    appended to the initcode.

    Returns deployed contract address.
    """
    node = call.node
    ctx = call.ctx

    ctx.check_is_not_constant("use create_from_blueprint", node)

    b = ctx.builder

    # Parse args: target is first, rest are ctor_args
    target = call.operand(node.args[0])
    ctor_arg_nodes = node.args[1:]

    # Parse kwargs
    code_offset = call.kwarg("code_offset")
    raw_args = call.literal("raw_args")
    revert_on_failure = call.literal("revert_on_failure")

    # Handle constructor arguments
    args_len: IROperand
    args_ptr: IROperand
    args_max_size: Optional[int]
    runtime_args = False

    if raw_args:
        # raw_args=True: single bytes argument contains raw constructor args
        # Semantic analysis validates raw_args=True has exactly one bytes argument.
        assert len(ctor_arg_nodes) == 1

        raw_arg_typ = ctor_arg_nodes[0]._metadata["type"]
        runtime_args = type_contains_unbounded_sequence(raw_arg_typ)
        raw_arg_vv = call.value(ctor_arg_nodes[0])
        raw_arg = raw_arg_vv.operand
        assert isinstance(raw_arg, IRVariable)
        args_len = b.mload(raw_arg)
        args_ptr = b.add(raw_arg, IRLiteral(32))
        args_max_size = None if runtime_args else raw_arg_typ.maxlen
    elif len(ctor_arg_nodes) > 0:
        ctor_tuple_typ, ctor_arg_vvs, runtime_ctor_args, ctor_abi_size = _prepare_ctor_args(
            call, ctor_arg_nodes
        )
        runtime_args = runtime_ctor_args

        if runtime_ctor_args:
            args_ptr = ctx.allocate_scratch(ctor_abi_size)
            args_max_size = None
        else:
            assert isinstance(ctor_abi_size, IRLiteral)
            args_buf = ctx.allocate_buffer(ctor_abi_size.value, annotation="ctor_args_buf")
            args_ptr = args_buf._ptr
            args_max_size = ctor_abi_size.value
        assert isinstance(args_ptr, IRVariable)
        args_len = _encode_ctor_args_to_buf(ctx, args_ptr, ctor_tuple_typ, ctor_arg_vvs)
    else:
        # No constructor arguments
        args_len = IRLiteral(0)
        args_ptr = IRLiteral(0)
        args_max_size = 0

    value = call.kwarg("value")

    salt: Optional[IROperand] = None
    if call.was_provided("salt"):
        salt = call.kwarg("salt")

    # Compare before subtraction so an oversized offset cannot wrap.
    full_codesize = b.extcodesize(target)
    has_code = b.gt(full_codesize, code_offset)
    codesize = b.sub(full_codesize, code_offset)
    b.assert_(has_code)

    # Total length = codesize + args_len. When args_len is literal 0,
    # algebraic optimization folds `add(codesize, 0) -> codesize`.
    total_len = ctx.checked_add(codesize, args_len) if runtime_args else b.add(codesize, args_len)
    mem_ofst = ctx.allocate_scratch(total_len)

    # Copy blueprint code (skipping preamble) to memory
    b.extcodecopy(target, mem_ofst, code_offset, codesize)

    # Append constructor args after code (copy from pre-encoded buffer)
    if not isinstance(args_len, IRLiteral) or args_len.value > 0:
        args_dest = b.add(mem_ofst, codesize)
        ctx.copy_memory_dynamic(args_dest, args_ptr, args_len, args_max_size)

    # Runtime-sized ctor args make total_len runtime-controlled. Oversized
    # initcode aborts the whole frame at CREATE (EIP-3860), so pre-check the
    # limit like raw_create does; bounded args keep the static path.
    return _emit_create(ctx, b, value, mem_ofst, total_len, salt, revert_on_failure, runtime_args)


HANDLERS = {
    "raw_create": lower_raw_create,
    "create_minimal_proxy_to": lower_create_minimal_proxy_to,
    "create_copy_of": lower_create_copy_of,
    "create_from_blueprint": lower_create_from_blueprint,
}

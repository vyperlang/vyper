from vyper.codegen_venom.module import generate_runtime_venom
from vyper.compiler import compile_code
from vyper.compiler.phases import CompilerData
from vyper.compiler.settings import Settings, anchor_settings
from vyper.venom.basicblock import IRLiteral, IRVariable


def _compile_frontend_ir(source):
    settings = Settings(experimental_codegen=True)
    with anchor_settings(settings):
        compiler_data = CompilerData(source, settings=settings)
        return generate_runtime_venom(compiler_data.global_ctx, settings)


def _opcodes(ctx):
    return [
        inst.opcode
        for fn in ctx.functions.values()
        for bb in fn.get_basic_blocks()
        for inst in bb.instructions
    ]


def _instructions(ctx):
    return [
        inst
        for fn in ctx.functions.values()
        for bb in fn.get_basic_blocks()
        for inst in bb.instructions
    ]


def test_inf_bytes_local_emits_dalloca():
    code = """
@external
def foo() -> Bytes[5]:
    x: Bytes[INF] = b"hello"
    return slice(x, 0, 5)
    """

    opcodes = _opcodes(_compile_frontend_ir(code))
    assert "dalloca" in opcodes


def test_bounded_bytes_local_stays_static_alloca():
    code = """
@external
def foo() -> Bytes[5]:
    x: Bytes[5] = b"hello"
    return x
    """

    opcodes = _opcodes(_compile_frontend_ir(code))
    assert "dalloca" not in opcodes


def test_inf_string_local_emits_dalloca():
    code = """
@external
def foo() -> String[5]:
    x: String[INF] = "hello"
    return slice(x, 0, 5)
    """

    opcodes = _opcodes(_compile_frontend_ir(code))
    assert "dalloca" in opcodes


def test_bounded_string_local_stays_static_alloca():
    code = """
@external
def foo() -> String[5]:
    x: String[5] = "hello"
    return x
    """

    opcodes = _opcodes(_compile_frontend_ir(code))
    assert "dalloca" not in opcodes


def test_inf_dynarray_local_emits_dalloca():
    code = """
@external
def foo() -> DynArray[uint256, INF]:
    x: DynArray[uint256, INF] = [1, 2, 3]
    return x
    """

    opcodes = _opcodes(_compile_frontend_ir(code))
    assert "dalloca" in opcodes


def test_bounded_dynarray_local_stays_static_alloca():
    code = """
@external
def foo() -> DynArray[uint256, 3]:
    x: DynArray[uint256, 3] = [1, 2, 3]
    return x
    """

    opcodes = _opcodes(_compile_frontend_ir(code))
    assert "dalloca" not in opcodes


def test_inf_bytes_external_return_emits_dalloca():
    code = """
@external
def foo() -> Bytes[INF]:
    return b"hello"
    """

    opcodes = _opcodes(_compile_frontend_ir(code))
    assert "dalloca" in opcodes


def test_internal_dynamic_tuple_return_copies_bounded_member_with_dret():
    code = """
@internal
def _pair(x: Bytes[INF]) -> (Bytes[4], Bytes[INF]):
    return b"abcd", x

@external
def pair(x: Bytes[INF]) -> (Bytes[4], Bytes[INF]):
    return self._pair(x)
    """

    insts = _instructions(_compile_frontend_ir(code))
    dret_counts = [
        inst.operands[0].value
        for inst in insts
        if inst.opcode == "dret" and isinstance(inst.operands[0], IRLiteral)
    ]
    assert 2 in dret_counts


def test_msg_data_rvalue_emits_dalloca_and_calldatacopy():
    code = """
@external
def foo() -> Bytes[INF]:
    return msg.data
    """

    opcodes = _opcodes(_compile_frontend_ir(code))
    assert "dalloca" in opcodes
    assert "calldatacopy" in opcodes


def _literal_or_assigned_literal(operand, definitions):
    if isinstance(operand, IRLiteral):
        return operand.value

    if isinstance(operand, IRVariable):
        definition = definitions.get(operand)
        if definition is not None and len(definition.operands) == 1:
            value = definition.operands[0]
            if isinstance(value, IRLiteral):
                return value.value

    return None


def _memory_copy_sizes(insts, definitions):
    sizes = []
    for inst in insts:
        if inst.opcode == "mcopy":
            sizes.append(_literal_or_assigned_literal(inst.operands[0], definitions))
            continue

        # Pre-Cancun memory-to-memory copies use the identity precompile:
        # staticcall(gas, 4, src, size, dst, size). EVM-ordered operands are
        # reversed in Venom IR, so [0] and [2] are the output/input sizes.
        if inst.opcode == "staticcall":
            ret_size = _literal_or_assigned_literal(inst.operands[0], definitions)
            arg_size = _literal_or_assigned_literal(inst.operands[2], definitions)
            target = _literal_or_assigned_literal(inst.operands[4], definitions)
            if target == 4 and ret_size == arg_size:
                sizes.append(ret_size)

    return sizes


def test_bounded_bytes_abi_decode_uses_static_maxbound_copy():
    code = """
@external
def dec(x: Bytes[INF]) -> Bytes[100]:
    return abi_decode(x, Bytes[100], unwrap_tuple=False)
    """

    ctx = compile_code(
        code, output_formats=["ir_runtime"], settings=Settings(experimental_codegen=True)
    )["ir_runtime"]
    insts = [
        inst
        for fn in ctx.functions.values()
        for bb in fn.get_basic_blocks()
        for inst in bb.instructions
    ]
    definitions = {inst._outputs[0]: inst for inst in insts if len(inst._outputs) == 1}
    copy_lengths = _memory_copy_sizes(insts, definitions)

    assert 160 in copy_lengths


def test_inf_abi_decode_checks_length_word_before_mload():
    code = """
@external
def dec(x: Bytes[INF]) -> Bytes[INF]:
    return abi_decode(x, Bytes[INF], unwrap_tuple=False)
    """

    ctx = _compile_frontend_ir(code)
    insts = [
        inst
        for fn in ctx.functions.values()
        for bb in fn.get_basic_blocks()
        for inst in bb.instructions
    ]
    defs = {inst._outputs[0]: i for i, inst in enumerate(insts) if len(inst._outputs) == 1}

    def _is_literal_32(op):
        return isinstance(op, IRLiteral) and op.value == 32

    found_checked_length_mload = False
    for i, inst in enumerate(insts):
        if inst.opcode != "mload":
            continue

        ptr = inst.operands[0]
        ptr_def = insts[defs[ptr]]
        if ptr_def.opcode != "add":
            continue
        if not any(isinstance(op, IRLiteral) and op.value == 32 for op in ptr_def.operands):
            continue

        precheck_adds = [
            j
            for j, candidate in enumerate(insts[:i])
            if candidate.opcode == "add"
            and len(candidate.operands) == 2
            and any(op == ptr for op in candidate.operands)
            and any(_is_literal_32(op) for op in candidate.operands)
        ]
        if precheck_adds and any(
            candidate.opcode == "assert" for candidate in insts[precheck_adds[-1] : i]
        ):
            found_checked_length_mload = True
            break

    assert found_checked_length_mload, "expected ABI length mload to be guarded by src + 32 check"


def test_inf_bytes_internal_return_emits_dret():
    code = """
@internal
def _bar() -> Bytes[INF]:
    x: Bytes[INF] = b"hello"
    return x

@external
def foo() -> Bytes[INF]:
    return self._bar()
    """

    opcodes = _opcodes(_compile_frontend_ir(code))
    assert "dret" in opcodes
    assert "invoke" in opcodes


def test_inf_dynarray_internal_return_emits_dret():
    code = """
@internal
def _bar() -> DynArray[uint256, INF]:
    x: DynArray[uint256, INF] = [1, 2, 3]
    return x

@external
def foo() -> DynArray[uint256, INF]:
    return self._bar()
    """

    opcodes = _opcodes(_compile_frontend_ir(code))
    assert "dret" in opcodes
    assert "invoke" in opcodes


def test_inf_bytes_external_param_emits_dalloca_and_calldatacopy():
    code = """
@external
def echo(x: Bytes[INF]) -> Bytes[INF]:
    return x
    """

    opcodes = _opcodes(_compile_frontend_ir(code))
    assert "dalloca" in opcodes
    assert "calldatacopy" in opcodes


def test_inf_bytes_staticcall_return_emits_dalloca_and_returndatacopy():
    code = """
interface Source:
    def data() -> Bytes[INF]: view

@external
def get(addr: address) -> Bytes[INF]:
    return staticcall Source(addr).data()
    """

    opcodes = _opcodes(_compile_frontend_ir(code))
    assert "dalloca" in opcodes
    assert "returndatacopy" in opcodes


def test_wildcard_tuple_interface_arg_uses_concrete_layout():
    code = """
interface I:
    def foo(x: (Bytes[...], uint256)) -> uint256: view

@external
def f(a: address, b: Bytes[10]) -> uint256:
    return staticcall I(a).foo((b, 1))
    """

    compile_code(code, output_formats=["bytecode"], settings=Settings(experimental_codegen=True))


def _dalloca_size_add32_depths(ctx):
    """For each dalloca, count trailing `add _, 32` steps feeding its size operand."""
    depths = []
    for fn in ctx.functions.values():
        definitions = {}
        for bb in fn.get_basic_blocks():
            for inst in bb.instructions:
                for out in inst.get_outputs():
                    definitions[out] = inst
        for bb in fn.get_basic_blocks():
            for inst in bb.instructions:
                if inst.opcode != "dalloca":
                    continue
                op = inst.operands[0]
                depth = 0
                while (d := definitions.get(op)) is not None:
                    if d.opcode == "store":
                        op = d.operands[0]
                        continue
                    non_literals = [o for o in d.operands if not isinstance(o, IRLiteral)]
                    if (
                        d.opcode == "add"
                        and len(non_literals) == 1
                        and any(isinstance(o, IRLiteral) and o.value == 32 for o in d.operands)
                    ):
                        depth += 1
                        op = non_literals[0]
                        continue
                    break
                depths.append(depth)
    return depths


def test_unbounded_concat_bytesm_output_reserves_slack_word():
    # a trailing bytesM arg is written with a full 32-byte mstore that can
    # extend past ceil32(total_len), so the concat output buffer must reserve
    # an extra word. differential vs a Bytes[4] literal arg, which takes the
    # byte-precise copy path and needs no slack.
    bytesm = """
@external
def join(x: Bytes[INF]) -> Bytes[INF]:
    return concat(x, 0xdeadbeef)
    """
    control = """
@external
def join(x: Bytes[INF]) -> Bytes[INF]:
    return concat(x, b"\\xde\\xad\\xbe\\xef")
    """

    bytesm_depths = _dalloca_size_add32_depths(_compile_frontend_ir(bytesm))
    control_depths = _dalloca_size_add32_depths(_compile_frontend_ir(control))
    assert len(bytesm_depths) == len(control_depths)
    assert sum(bytesm_depths) == sum(control_depths) + 1


def _has_tail_padding_mask_store(ctx):
    """Find mstore(ptr, and(mload(ptr), 0xffffffff << 224)).

    This is the masked store that re-zeroes the 28 padding bytes after the
    last 4 data bytes of an INF abi_encode result with a method_id prefix.
    """
    keep_data_mask = ((1 << 32) - 1) << 224
    for fn in ctx.functions.values():
        definitions = {}
        for bb in fn.get_basic_blocks():
            for inst in bb.instructions:
                for out in inst.get_outputs():
                    definitions[out] = inst
        for bb in fn.get_basic_blocks():
            for inst in bb.instructions:
                if inst.opcode != "mstore":
                    continue
                for val_op in inst.operands:
                    ptr_ops = [op for op in inst.operands if op is not val_op]
                    and_inst = definitions.get(val_op)
                    if and_inst is None or and_inst.opcode != "and":
                        continue
                    if not any(
                        isinstance(op, IRLiteral) and op.value == keep_data_mask
                        for op in and_inst.operands
                    ):
                        continue
                    for and_op in and_inst.operands:
                        mload_inst = definitions.get(and_op)
                        if mload_inst is None or mload_inst.opcode != "mload":
                            continue
                        if mload_inst.operands[0] in ptr_ops:
                            return True
    return False


def test_inf_abi_encode_method_id_zeroes_tail_padding_at_runtime_length():
    # with a method_id prefix, the encoded value's last word holds 4 data
    # bytes followed by 28 padding bytes at buf+32+encoded_len. encoded_len
    # is only known at runtime and can be smaller than the allocation
    # estimate (bounded dynamic args are sized by their bound), so the
    # padding must be zeroed relative to the runtime encoded length, via a
    # masked read-modify-write of that word. differential vs the same encode
    # without method_id, whose total length is a word multiple and has no
    # partial last word.
    with_method_id = """
@external
def enc(x: Bytes[INF], d: DynArray[uint256, 4]) -> Bytes[INF]:
    return abi_encode(x, d, method_id=0xa1b2c3d4)
    """
    without_method_id = """
@external
def enc(x: Bytes[INF], d: DynArray[uint256, 4]) -> Bytes[INF]:
    return abi_encode(x, d)
    """
    bounded = """
@external
def enc(x: Bytes[32], d: DynArray[uint256, 4]) -> Bytes[300]:
    return abi_encode(x, d, method_id=0xa1b2c3d4)
    """

    assert _has_tail_padding_mask_store(_compile_frontend_ir(with_method_id))
    assert not _has_tail_padding_mask_store(_compile_frontend_ir(without_method_id))
    # bounded path is unchanged (no masked store there)
    assert not _has_tail_padding_mask_store(_compile_frontend_ir(bounded))

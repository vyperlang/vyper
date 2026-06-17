from vyper.codegen_venom.module import generate_runtime_venom
from vyper.compiler import compile_code
from vyper.compiler.phases import CompilerData
from vyper.compiler.settings import Settings, anchor_settings
from vyper.venom.basicblock import IRLiteral


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


def test_msg_data_rvalue_emits_dalloca_and_calldatacopy():
    code = """
@external
def foo() -> Bytes[INF]:
    return msg.data
    """

    opcodes = _opcodes(_compile_frontend_ir(code))
    assert "dalloca" in opcodes
    assert "calldatacopy" in opcodes


def test_bounded_bytes_abi_decode_copies_runtime_payload_only():
    code = """
@external
def dec(x: Bytes[INF]) -> Bytes[100]:
    return abi_decode(x, Bytes[100], unwrap_tuple=False)
    """

    ctx = compile_code(
        code, output_formats=["ir_runtime"], settings=Settings(experimental_codegen=True)
    )["ir_runtime"]
    mcopy_lengths = [
        inst.operands[0]
        for fn in ctx.functions.values()
        for bb in fn.get_basic_blocks()
        for inst in bb.instructions
        if inst.opcode == "mcopy"
    ]

    assert not any(
        isinstance(length, IRLiteral) and length.value == 160 for length in mcopy_lengths
    )


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

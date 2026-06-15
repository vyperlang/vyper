from vyper.codegen_venom.module import generate_runtime_venom
from vyper.compiler.phases import CompilerData
from vyper.compiler.settings import Settings


def _compile_frontend_ir(source):
    settings = Settings(experimental_codegen=True)
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

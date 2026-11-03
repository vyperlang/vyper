import pytest

from vyper.codegen_venom.module import generate_venom_runtime
from vyper.compiler.phases import CompilerData
from vyper.compiler.settings import OptimizationLevel, Settings, anchor_settings
from vyper.venom.basicblock import IRLiteral, IRVariable


def _runtime_venom(code: str):
    # the IR straight out of codegen, before any pass
    settings = Settings(experimental_codegen=True, optimize=OptimizationLevel.NONE)
    compiler_data = CompilerData(code, settings=settings)
    with anchor_settings(compiler_data.settings):
        return generate_venom_runtime(compiler_data.global_ctx, compiler_data.settings)


def _check_loads_in_bounds(ctx):
    """Check each `mload` at a literal offset from an alloca reads inside it,
    and return how many such loads there are."""
    count = 0
    for fn in ctx.functions.values():
        insts = [inst for bb in fn.get_basic_blocks() for inst in bb.instructions]
        alloca_size = {}
        for inst in insts:
            if inst.opcode == "alloca":
                alloca_size[inst.output] = inst.operands[0].value
        # (alloca size, offset) of each pointer at a literal offset into an alloca
        ptr = {var: (size, 0) for var, size in alloca_size.items()}
        for inst in insts:
            if inst.opcode != "add":
                continue
            a, b = inst.operands
            if isinstance(a, IRLiteral) and b in alloca_size:
                ptr[inst.output] = (alloca_size[b], a.value)
            elif isinstance(b, IRLiteral) and a in alloca_size:
                ptr[inst.output] = (alloca_size[a], b.value)
        for inst in insts:
            if inst.opcode != "mload":
                continue
            (addr,) = inst.operands
            if isinstance(addr, IRVariable) and addr in ptr:
                size, offset = ptr[addr]
                assert offset + 32 <= size, inst
                count += 1
    return count


@pytest.mark.parametrize(
    "src,out_typ",
    [('b""', "bool"), ('b""', "uint256"), ('b""', "int256"), ('b""', "bytes32"), ('""', "bool")],
)
def test_zero_capacity_bytestring_convert_is_not_read_past(src, out_typ):
    # a zero-capacity bytestring's buffer is its length word alone
    code = f"""
@external
def f() -> {out_typ}:
    return convert({src}, {out_typ})
    """
    _check_loads_in_bounds(_runtime_venom(code))

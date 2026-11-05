import pytest

from vyper.codegen_venom.module import generate_venom_runtime
from vyper.compiler.phases import CompilerData
from vyper.compiler.settings import OptimizationLevel, Settings, anchor_settings
from vyper.venom.basicblock import IRLiteral, IRVariable


def _runtime_venom(code: str):
    # the IR straight out of codegen, before any pass. cancun, so memory
    # copies are `mcopy` whatever evm version the test run targets
    settings = Settings(
        experimental_codegen=True, optimize=OptimizationLevel.NONE, evm_version="cancun"
    )
    compiler_data = CompilerData(code, settings=settings)
    with anchor_settings(compiler_data.settings):
        return generate_venom_runtime(compiler_data.global_ctx, compiler_data.settings)


def _check_reads_in_bounds(ctx):
    """Check each `mload`, and each fixed-size `mcopy`, at a literal offset
    from an alloca reads inside it, and that no fixed-size `mcopy` reads
    from a runtime-sized `dalloca`."""
    for fn in ctx.functions.values():
        insts = [inst for bb in fn.get_basic_blocks() for inst in bb.instructions]
        alloca_size = {}
        dallocas = set()
        for inst in insts:
            if inst.opcode == "alloca":
                alloca_size[inst.output] = inst.operands[0].value
            elif inst.opcode == "dalloca":
                dallocas.add(inst.output)
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
            if inst.opcode == "mload":
                (addr,) = inst.operands
                read_size = 32
            elif inst.opcode == "mcopy":
                size, addr, _ = inst.operands  # reversed: dst, src, size
                if not isinstance(size, IRLiteral):
                    continue
                assert addr not in dallocas, inst
                read_size = size.value
            else:
                continue
            if isinstance(addr, IRVariable) and addr in ptr:
                size, offset = ptr[addr]
                assert offset + read_size <= size, inst


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
    _check_reads_in_bounds(_runtime_venom(code))


@pytest.mark.parametrize(
    "arg_typ,expr,ret_typ",
    [
        # a cast to a wider bound, then read as the wider type
        ("bool", 'convert(convert("", Bytes[1]), int256)', "int256"),
        ("String[2]", "convert(x, Bytes[40])", "Bytes[40]"),
        ("Bytes[2]", "convert(x, String[40])", "String[40]"),
        # a cast of an unbounded value, whose buffer has its runtime size
        ("Bytes[INF]", "convert(x, String[40])", "String[40]"),
    ],
)
def test_widening_bytestring_convert_is_not_read_past(arg_typ, expr, ret_typ):
    code = f"""
@external
def f(x: {arg_typ}) -> {ret_typ}:
    y: {ret_typ} = {expr}
    return y
    """
    _check_reads_in_bounds(_runtime_venom(code))

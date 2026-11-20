import pytest

from vyper.codegen_venom.module import generate_venom_runtime
from vyper.compiler.phases import CompilerData
from vyper.compiler.settings import OptimizationLevel, Settings, anchor_settings
from vyper.venom.basicblock import IRLiteral


def _runtime_venom(code: str):
    # the IR straight out of codegen, before any pass. cancun, so memory
    # copies are `mcopy` whatever evm version the test run targets
    settings = Settings(
        experimental_codegen=True, optimize=OptimizationLevel.NONE, evm_version="cancun"
    )
    compiler_data = CompilerData(code, settings=settings)
    with anchor_settings(compiler_data.settings):
        return generate_venom_runtime(compiler_data.global_ctx, compiler_data.settings)


def _note(ptr, var, alloca, offset):
    """Record `offset` as a bound on `var`'s offset into `alloca`;
    return whether it raised the bound."""
    bounds = ptr.setdefault(var, {})
    if bounds.get(alloca, -1) < offset:
        bounds[alloca] = offset
        return True
    return False


def _check_reads_in_bounds(ctx):
    """Check each `mload`, and each `mcopy` with a static bound on its size,
    through a pointer into an alloca stays inside it.

    A pointer's offset is bounded from above: `add` of a literal adds to it,
    `sub` of anything leaves it (uint2str moves its result pointer down from
    the end of the digits), and an `assign` merges the bounds of its sources.
    """
    for fn in ctx.functions.values():
        insts = [inst for bb in fn.get_basic_blocks() for inst in bb.instructions]
        alloca_size = {}
        # pointer -> {alloca: largest offset into it}
        ptr: dict = {}

        for inst in insts:
            if inst.opcode == "alloca":
                alloca_size[inst.output] = inst.operands[0].value
                _note(ptr, inst.output, inst.output, 0)

        # iterate to a fixpoint: a loop can assign a pointer before its uses
        changed = True
        while changed:
            changed = False
            for inst in insts:
                if inst.opcode == "add":
                    a, b = inst.operands
                    if isinstance(a, IRLiteral):
                        a, b = b, a
                    if not isinstance(b, IRLiteral):
                        continue
                    for alloca, offset in list(ptr.get(a, {}).items()):
                        changed |= _note(ptr, inst.output, alloca, offset + b.value)
                elif inst.opcode == "sub":
                    # `sub x, y`: operands are stored reversed
                    _, a = inst.operands
                    for alloca, offset in list(ptr.get(a, {}).items()):
                        changed |= _note(ptr, inst.output, alloca, offset)
                elif inst.opcode == "assign":
                    (a,) = inst.operands
                    for alloca, offset in list(ptr.get(a, {}).items()):
                        changed |= _note(ptr, inst.output, alloca, offset)

        for inst in insts:
            if inst.opcode == "mload":
                (addr,) = inst.operands
                read_size = 32
            elif inst.opcode == "mcopy":
                size, addr, _ = inst.operands  # reversed: dst, src, size
                if isinstance(size, IRLiteral):
                    read_size = size.value
                elif inst.memory_read_max_size is not None:
                    read_size = inst.memory_read_max_size
                else:
                    continue
            else:
                continue
            for alloca, offset in ptr.get(addr, {}).items():
                assert offset + read_size <= alloca_size[alloca], inst


@pytest.mark.parametrize("int_typ", ["uint8", "uint256"])
@pytest.mark.parametrize(
    "body",
    [
        "x: STR = uint2str(y)",
        "t: S = S(s=uint2str(y))",
        "a: DynArray[STR, 2] = [uint2str(y)]",
        "self.a.append(uint2str(y))",
        "self.g(uint2str(y))",
    ],
)
def test_uint2str_result_is_not_read_past(int_typ, body):
    # uint2str's result points into the middle of its buffer, where its
    # digits start; a consumer may read a full String[n] from there
    n = {"uint8": 3, "uint256": 78}[int_typ]
    code = f"""
struct S:
    s: String[{n}]

a: DynArray[String[{n}], 2]

@internal
def g(s: String[{n}]):
    pass

@external
def f(y: {int_typ}):
    {body.replace("STR", f"String[{n}]")}
    """
    _check_reads_in_bounds(_runtime_venom(code))

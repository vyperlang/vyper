from collections import defaultdict

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


def _alloca_sizes(defs, var, seen):
    """Sizes of the allocas `var` can point to the start of, following
    assigns (codegen joins the ternary arms by assigning to one variable)."""
    if var in seen:
        return []
    seen.add(var)
    sizes = []
    for inst in defs[var]:
        src = inst.operands[0] if inst.operands else None
        if inst.opcode == "alloca":
            sizes.append(src.value)
        elif inst.opcode == "assign" and isinstance(src, IRVariable):
            sizes.extend(_alloca_sizes(defs, src, seen))
    return sizes


def _check_copies_in_bounds(ctx):
    """Check each fixed-size mcopy fits the allocas its source can be, and
    return the copy sizes."""
    sizes = []
    for fn in ctx.functions.values():
        insts = [inst for bb in fn.get_basic_blocks() for inst in bb.instructions]
        defs = defaultdict(list)
        for inst in insts:
            for out in inst.get_outputs():
                defs[out].append(inst)
        for inst in insts:
            if inst.opcode != "mcopy":
                continue
            size, src, _ = inst.operands  # reversed: dst, src, size
            if not (isinstance(size, IRLiteral) and isinstance(src, IRVariable)):
                continue
            sizes.append(size.value)
            for buf_size in _alloca_sizes(defs, src, set()):
                assert size.value <= buf_size, inst

    return sizes


@pytest.mark.parametrize("arms", ["x if c else b'hello'", "b'hello' if c else x", "x if c else y"])
def test_narrower_bytestring_arm_is_not_read_past(arms):
    # each arm points into its own buffer; the result is read as Bytes[40],
    # so a narrower arm must not be read with the result's 96-byte size
    code = f"""
@external
def f(c: bool, x: Bytes[40], y: Bytes[10]) -> Bytes[40]:
    z: Bytes[40] = {arms}
    return z
    """
    assert 96 in _check_copies_in_bounds(_runtime_venom(code))


def test_narrower_dynarray_arm_is_not_read_past():
    code = """
@external
def f(c: bool, x: DynArray[uint256, 5], y: DynArray[uint256, 2]) -> DynArray[uint256, 5]:
    z: DynArray[uint256, 5] = x if c else y
    return z
    """
    assert 192 in _check_copies_in_bounds(_runtime_venom(code))

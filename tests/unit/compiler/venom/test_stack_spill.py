from __future__ import annotations

import pytest

from vyper.venom.basicblock import IRLiteral, IRVariable
from vyper.venom.context import IRContext
from vyper.venom.stack_model import StackModel
from vyper.venom.venom_to_assembly import VenomCompiler


@pytest.fixture
def compiler() -> VenomCompiler:
    ctx = IRContext()
    ctx.add_constant("mem_deploy_end", 0)
    return VenomCompiler(ctx)


def _build_stack(count: int) -> tuple[StackModel, list[IRLiteral]]:
    stack = StackModel()
    ops = [IRLiteral(i) for i in range(count)]
    for op in ops:
        stack.push(op)
    return stack, ops


def _ops_only_strings(assembly) -> list[str]:
    return [op for op in assembly if isinstance(op, str)]


def _dummy_dfg():
    class _DummyDFG:
        def are_equivalent(self, a, b):
            return False

    return _DummyDFG()


def test_swap_spills_deep_stack(compiler: VenomCompiler) -> None:
    stack, ops = _build_stack(40)
    assembly: list = []

    target = ops[-18]
    before = stack._stack.copy()

    depth = stack.get_depth(target)
    assert isinstance(depth, int) and depth < -16
    swap_idx = -depth

    compiler.swap(assembly, stack, depth)

    expected = before.copy()
    top_index = len(expected) - 1
    target_index = expected.index(target)
    expected[top_index], expected[target_index] = expected[target_index], expected[top_index]
    assert stack._stack == expected

    ops_str = _ops_only_strings(assembly)
    assert ops_str.count("MSTORE") == swap_idx + 1
    assert ops_str.count("MLOAD") == swap_idx + 1
    assert all(int(op[4:]) <= 16 for op in ops_str if op.startswith("SWAP"))


def test_dup_spills_deep_stack(compiler: VenomCompiler) -> None:
    stack, ops = _build_stack(40)
    assembly: list = []

    target = ops[-18]
    before = stack._stack.copy()

    depth = stack.get_depth(target)
    assert isinstance(depth, int) and depth < -16
    dup_idx = 1 - depth

    compiler.dup(assembly, stack, depth)

    expected = before.copy()
    expected.append(target)
    assert stack._stack == expected

    ops_str = _ops_only_strings(assembly)
    assert ops_str.count("MSTORE") == dup_idx
    assert ops_str.count("MLOAD") == dup_idx + 1
    assert all(int(op[3:]) <= 16 for op in ops_str if op.startswith("DUP"))


def test_stack_reorder_spills_before_swap(compiler: VenomCompiler) -> None:
    compiler.dfg = _dummy_dfg()
    compiler._spill_next_slot = 0
    compiler._spill_free_slots = []

    stack = StackModel()
    vars_on_stack = [IRVariable(f"%v{i}") for i in range(40)]
    for var in vars_on_stack:
        stack.push(var)

    spilled: dict = {}
    assembly: list = []

    target = vars_on_stack[21]  # depth 18 from top for 40 items

    compiler._stack_reorder(assembly, stack, [target], spilled, dry_run=False)

    assert stack.get_depth(target) == 0
    assert len(spilled) == 2  # spilled top two values to reduce depth to <= 16

    ops_str = _ops_only_strings(assembly)
    assert ops_str.count("MSTORE") == 2
    assert all(int(op[4:]) <= 16 for op in ops_str if op.startswith("SWAP"))

    # restoring a spilled variable should reload it via MLOAD
    restore_assembly: list = []
    spilled_var = next(iter(spilled))
    compiler._restore_spilled_operand(restore_assembly, stack, spilled, spilled_var)
    restore_ops = _ops_only_strings(restore_assembly)
    assert restore_ops.count("MLOAD") == 1
    assert spilled_var not in spilled
    assert stack.get_depth(spilled_var) == 0

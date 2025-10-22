from __future__ import annotations

import pytest

from vyper.venom.basicblock import IRLiteral
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

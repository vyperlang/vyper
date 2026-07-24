import pytest

from vyper.ir.compile_ir import Label
from vyper.venom.basicblock import IRLiteral, IROperand, IRVariable
from vyper.venom.context import IRContext
from vyper.venom.parser import parse_venom
from vyper.venom.stack_model import StackModel
from vyper.venom.venom_to_assembly import VenomCompiler


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


def test_set_current_function_clears_missing_fn_eom() -> None:
    ctx = parse_venom("""
        function first {
            main:
                stop
        }

        function second {
            main:
                stop
        }
        """)
    compiler = VenomCompiler(ctx)
    first, second = list(ctx.functions.values())

    ctx.mem_allocator.fn_eom[first] = 64
    compiler.spiller.set_current_function(first)
    assert compiler.spiller._next_spill_offset == 64

    compiler.spiller.set_current_function(second)
    assert compiler.spiller._next_spill_offset is None

    compiler.spiller._next_spill_offset = 96
    compiler.spiller.set_current_function(None)
    assert compiler.spiller._next_spill_offset is None


def test_swap_spills_deep_stack() -> None:
    compiler = VenomCompiler(IRContext())
    compiler.spiller._next_spill_offset = 0x10000  # Set up for unit test
    stack, ops = _build_stack(40)
    assembly: list = []

    target = ops[-18]
    before = stack._stack.copy()

    depth = stack.get_depth(target)
    assert isinstance(depth, int) and depth < -16
    swap_idx = -depth

    compiler.spiller.swap(assembly, stack, depth)

    expected = before.copy()
    top_index = len(expected) - 1
    target_index = expected.index(target)
    expected[top_index], expected[target_index] = expected[target_index], expected[top_index]
    assert stack._stack == expected

    ops_str = _ops_only_strings(assembly)
    assert ops_str.count("MSTORE") == swap_idx + 1
    assert ops_str.count("MLOAD") == swap_idx + 1
    assert all(int(op[4:]) <= 16 for op in ops_str if op.startswith("SWAP"))


def test_dup_spills_deep_stack() -> None:
    compiler = VenomCompiler(IRContext())
    compiler.spiller._next_spill_offset = 0x10000  # Set up for unit test
    stack, ops = _build_stack(40)
    assembly: list = []

    target = ops[-18]
    before = stack._stack.copy()

    depth = stack.get_depth(target)
    assert isinstance(depth, int) and depth < -16
    dup_idx = 1 - depth

    cost = compiler.spiller.dup(assembly, stack, depth)

    expected = before.copy()
    expected.append(target)
    assert stack._stack == expected

    ops_str = _ops_only_strings(assembly)
    spill_count = dup_idx - 16
    assert ops_str.count("MSTORE") == spill_count
    assert ops_str.count("MLOAD") == spill_count
    assert [op for op in ops_str if op.startswith("SWAP")] == [f"SWAP{spill_count}"]
    assert [op for op in ops_str if op.startswith("DUP")] == ["DUP16"]
    assert cost == 2 + 4 * spill_count


@pytest.mark.parametrize("dup_idx", range(16, 65))
def test_dup_stack_model(dup_idx: int) -> None:
    compiler = VenomCompiler(IRContext())
    compiler.spiller._next_spill_offset = 0x10000
    stack, ops = _build_stack(64)
    assembly: list = []

    target = ops[-dup_idx]
    before = stack._stack.copy()
    depth = stack.get_depth(target)
    assert depth == 1 - dup_idx

    cost = compiler.spiller.dup(assembly, stack, depth)

    assert stack._stack == before + [target]

    spill_count = max(0, dup_idx - 16)
    ops_str = _ops_only_strings(assembly)
    assert ops_str.count("MSTORE") == spill_count
    assert ops_str.count("MLOAD") == spill_count
    assert [op for op in ops_str if op.startswith("DUP")] == [f"DUP{min(dup_idx, 16)}"]

    expected_swaps: list[str] = []
    if 0 < spill_count <= 16:
        expected_swaps = [f"SWAP{spill_count}"]
    elif spill_count > 16:
        expected_swaps = ["SWAP1"] * spill_count
    assert [op for op in ops_str if op.startswith("SWAP")] == expected_swaps
    assert cost == 1 + 4 * spill_count + len(expected_swaps)


def test_deep_dup_reuses_spill_slots() -> None:
    compiler = VenomCompiler(IRContext())
    spiller = compiler.spiller
    first_slot = 0x10000
    spiller._spill_free_slots = [first_slot]
    spiller._next_spill_offset = first_slot + 32
    spiller.peak_spill_end = first_slot + 32

    for _ in range(2):
        stack, ops = _build_stack(18)
        before = stack._stack.copy()
        assembly: list = []

        spiller.dup(assembly, stack, stack.get_depth(ops[0]))

        assert stack._stack == before + [ops[0]]
        assert sorted(spiller._spill_free_slots) == [first_slot, first_slot + 32]
        assert spiller._next_spill_offset == first_slot + 64
        assert spiller.peak_spill_end == first_slot + 64


def test_deep_dup_dry_run_cost_matches_and_preserves_state() -> None:
    compiler = VenomCompiler(IRContext())
    spiller = compiler.spiller
    first_slot = 0x10000
    spiller._spill_free_slots = [first_slot]
    spiller._next_spill_offset = first_slot + 32
    spiller.peak_spill_end = first_slot + 32
    snap = spiller.snapshot()

    dry_stack, dry_ops = _build_stack(20)
    dry_before = dry_stack._stack.copy()
    dry_assembly: list = []
    dry_cost = spiller.dup(dry_assembly, dry_stack, dry_stack.get_depth(dry_ops[0]), dry_run=True)

    assert dry_stack._stack == dry_before + [dry_ops[0]]
    assert spiller.snapshot() == snap
    assert spiller.peak_spill_end == first_slot + 32

    stack, ops = _build_stack(20)
    before = stack._stack.copy()
    assembly: list = []
    cost = spiller.dup(assembly, stack, stack.get_depth(ops[0]))

    assert stack._stack == before + [ops[0]]
    assert cost == dry_cost == 18
    assert _ops_only_strings(assembly) == _ops_only_strings(dry_assembly)
    assert spiller._next_spill_offset == first_slot + 128
    assert spiller.peak_spill_end == first_slot + 128


def test_deep_dup_peak_spill_end_tracks_partial_prefix() -> None:
    compiler = VenomCompiler(IRContext())
    spiller = compiler.spiller
    first_slot = 0x10000
    spiller._next_spill_offset = first_slot
    stack, ops = _build_stack(64)

    spiller.dup([], stack, stack.get_depth(ops[0]))

    spill_count = 64 - 16
    expected_end = first_slot + spill_count * 32
    assert spiller._next_spill_offset == expected_end
    assert spiller.peak_spill_end == expected_end
    assert len(spiller._spill_free_slots) == spill_count


def test_partial_deep_dup_integration() -> None:
    ctx = IRContext()
    fn = ctx.create_function("deep_dup")
    bb = fn.get_basic_block()
    target = bb.append_instruction("calldataload", 0)
    values = [bb.append_instruction("calldataload", i) for i in range(1, 17)]

    # Keep the target and all intervening values live so copying target enters
    # the deep-DUP path at DUP17.
    acc = bb.append_instruction("add", target, 1)
    for value in values:
        acc = bb.append_instruction("add", acc, value)
    bb.append_instruction("add", acc, target)
    bb.append_instruction("stop")

    ctx.mem_allocator.fn_eom[fn] = 0x10000
    compiler = VenomCompiler(ctx)
    asm = compiler.generate_evm_assembly(no_optimize=True)
    opcodes = _ops_only_strings(asm)

    assert opcodes.count("MSTORE") == 1
    assert opcodes.count("MLOAD") == 1
    assert opcodes.count("DUP16") == 1
    store_idx = opcodes.index("MSTORE")
    assert opcodes[store_idx - 1 : store_idx + 5] == [
        "PUSH3",
        "MSTORE",
        "DUP16",
        "PUSH3",
        "MLOAD",
        "SWAP1",
    ]
    assert compiler.spiller.peak_spill_end == 0x10020


def test_stack_reorder_spills_before_swap() -> None:
    ctx = IRContext()
    compiler = VenomCompiler(ctx)
    compiler.dfg = _dummy_dfg()
    compiler.spiller._next_spill_offset = 0x10000  # Set up for unit test

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
    compiler.spiller.restore_spilled_operand(restore_assembly, stack, spilled, spilled_var)
    restore_ops = _ops_only_strings(restore_assembly)
    assert restore_ops.count("MLOAD") == 1
    assert spilled_var not in spilled
    assert stack.get_depth(spilled_var) == 0


def test_branch_spill_integration() -> None:
    venom_src = """
    function spill_demo {
        main:
            %v0 = mload 0
            %v1 = mload 32
            %v2 = mload 64
            %v3 = mload 96
            %v4 = mload 128
            %v5 = mload 160
            %v6 = mload 192
            %v7 = mload 224
            %v8 = mload 256
            %v9 = mload 288
            %v10 = mload 320
            %v11 = mload 352
            %v12 = mload 384
            %v13 = mload 416
            %v14 = mload 448
            %v15 = mload 480
            %v16 = mload 512
            %v17 = mload 544
            %v18 = mload 576
            %v19 = mload 608
            %cond = mload 640
            jnz %cond, @then, @else
        then:
            %then_sum = add %v0, %v19
            %res_then = add %then_sum, %cond
            jmp @join
        else:
            %else_sum = add %v1, %v19
            %res_else = add %else_sum, %cond
            jmp @join
        join:
            %phi = phi @then, %res_then, @else, %res_else
            %acc1 = add %phi, %v1
            %acc2 = add %acc1, %v2
            %acc3 = add %acc2, %v3
            %acc4 = add %acc3, %v4
            %acc5 = add %acc4, %v5
            %acc6 = add %acc5, %v6
            %acc7 = add %acc6, %v7
            %acc8 = add %acc7, %v8
            %acc9 = add %acc8, %v9
            %acc10 = add %acc9, %v10
            %acc11 = add %acc10, %v11
            %acc12 = add %acc11, %v12
            %acc13 = add %acc12, %v13
            %acc14 = add %acc13, %v14
            %acc15 = add %acc14, %v15
            %acc16 = add %acc15, %v16
            %acc17 = add %acc16, %v17
            %acc18 = add %acc17, %v18
            return %acc18
    }
    """

    ctx = parse_venom(venom_src)
    compiler = VenomCompiler(ctx)
    fn = next(iter(ctx.functions.values()))
    # generate_evm_assembly seeds the spill cursor per function via
    # set_current_function, which clears _next_spill_offset when fn is absent
    # from fn_eom -- presetting the private field directly would be
    # overwritten, so seed fn_eom instead. (test_swap_spills_deep_stack above
    # can still preset the field because it never goes through
    # generate_evm_assembly.)
    ctx.mem_allocator.fn_eom[fn] = 0x10000
    asm = compiler.generate_evm_assembly()
    opcodes = [op for op in asm if isinstance(op, str)]

    for op in opcodes:
        if op.startswith("SWAP"):
            assert int(op[4:]) <= 16
        if op.startswith("DUP"):
            assert int(op[3:]) <= 16

    def _find_spill_ops(kind: str) -> list[int]:
        matches: list[int] = []
        idx = 0
        while idx < len(asm):
            item = asm[idx]
            if isinstance(item, str) and item.startswith("PUSH"):
                try:
                    push_bytes = int(item[4:])
                except ValueError:
                    push_bytes = 0
                target_idx = idx + 1 + push_bytes
                if target_idx < len(asm) and asm[target_idx] == kind:
                    matches.append(idx)
                idx = target_idx + 1
            else:
                idx += 1
        return matches

    store_indices = _find_spill_ops("MSTORE")
    load_indices = _find_spill_ops("MLOAD")
    assert store_indices
    assert load_indices

    join_idx = next(
        idx for idx, op in enumerate(asm) if isinstance(op, Label) and str(op) == "LABEL join"
    )

    assert any(idx < join_idx for idx in store_indices)
    assert any(idx > join_idx for idx in store_indices)
    assert any(idx < join_idx for idx in load_indices)
    assert any(idx > join_idx for idx in load_indices)


def test_dup_op_operand_not_in_stack() -> None:
    compiler = VenomCompiler(IRContext())
    stack = StackModel()
    assembly: list = []

    ops = [IRVariable(f"%{i}") for i in range(5)]
    for op in ops:
        stack.push(op)

    not_in_stack = IRVariable("%99")

    with pytest.raises(AssertionError):
        compiler.dup_op(assembly, stack, not_in_stack)


def test_stack_reorder_operand_not_in_stack_but_spilled() -> None:
    ctx = IRContext()
    compiler = VenomCompiler(ctx)
    compiler.dfg = _dummy_dfg()

    stack = StackModel()
    for i in range(5):
        stack.push(IRVariable(f"%{i}"))

    spilled_var = IRVariable("%spilled")
    spilled: dict = {spilled_var: 0x10000}

    assembly: list = []

    # Try to reorder with spilled_var as target (should restore it from memory)
    compiler._stack_reorder(assembly, stack, [spilled_var], spilled, dry_run=False)

    # Should have restored the spilled variable
    assert stack.get_depth(spilled_var) == 0  # Should be on top of stack
    assert spilled_var not in spilled  # Should have been removed from spilled dict
    # Assembly should contain PUSH and MLOAD to restore
    assert "MLOAD" in assembly


def test_stack_spill_stack_invalidation_error():
    dummy_function = """
    function spill_demo {
    main:
        ret 0
    }
    """

    ctx = parse_venom(dummy_function)
    compiler = VenomCompiler(ctx)
    compiler.dfg = _dummy_dfg()
    compiler.spiller._current_function = next(ctx.get_functions())
    compiler.spiller._next_spill_offset = 0x1000

    stack = StackModel()
    a = IRVariable("%a")
    b = IRVariable("%b")

    expected_stack: list[IROperand] = [a, b]

    stack.push(b)
    for i in range(20):
        stack.push(IRVariable(f"%{i}"))
    stack.push(a)

    spilled: dict = {}

    assembly: list = []

    # Try to reorder with spilled_var as target (should restore it from memory)
    compiler._stack_reorder(assembly, stack, expected_stack, spilled, dry_run=False)

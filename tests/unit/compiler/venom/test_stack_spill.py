from vyper.ir.compile_ir import Label
from vyper.venom.basicblock import IRLiteral, IRVariable
from vyper.venom.context import IRContext
from vyper.venom.parser import parse_venom
from vyper.venom.stack_model import StackModel
from vyper.venom.stack_spiller import StackSpiller
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


def test_swap_spills_deep_stack() -> None:
    compiler = VenomCompiler(IRContext())
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
    stack, ops = _build_stack(40)
    assembly: list = []

    target = ops[-18]
    before = stack._stack.copy()

    depth = stack.get_depth(target)
    assert isinstance(depth, int) and depth < -16
    dup_idx = 1 - depth

    compiler.spiller.dup(assembly, stack, depth)

    expected = before.copy()
    expected.append(target)
    assert stack._stack == expected

    ops_str = _ops_only_strings(assembly)
    assert ops_str.count("MSTORE") == dup_idx
    assert ops_str.count("MLOAD") == dup_idx + 1
    assert all(int(op[3:]) <= 16 for op in ops_str if op.startswith("DUP"))


def test_stack_reorder_spills_before_swap() -> None:
    ctx = IRContext()
    compiler = VenomCompiler(ctx)
    compiler.dfg = _dummy_dfg()

    compiler.spiller = StackSpiller(ctx, initial_offset=0x10000)

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
    compiler.generate_evm_assembly()

    fn = next(iter(ctx.functions.values()))
    assert any(inst.opcode == "alloca" for inst in fn.entry.instructions)

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

"""
Memory fuzzer for Venom IR.

This fuzzer generates complex control flow with memory instructions to test
memory optimization passes. It uses the IRBasicBlock API directly and
can be plugged with any Venom passes.
"""

from dataclasses import dataclass
from typing import Optional

import hypothesis as hp
import hypothesis.strategies as st
import pytest

from vyper.venom.analysis import IRAnalysesCache
from vyper.venom.basicblock import IRBasicBlock, IRInstruction, IRLabel, IRLiteral, IRVariable
from vyper.venom.context import IRContext
from vyper.venom.function import IRFunction
from vyper.venom.passes import DeadStoreElimination,LoadElimination, MemMergePass

MEMORY_OPS = ["mload", "mstore", "mcopy"]

# precompiles act as fence operations that generate real output data,
# preventing optimizers from eliminating memory operations
PRECOMPILES = {
    0x1: "ecrecover",
    0x2: "sha256",
    0x3: "ripemd160",
    0x4: "identity",
    0x5: "modexp",
    0x6: "ecadd",
    0x7: "ecmul",
    0x8: "ecpairing",
    0x9: "blake2f",
}

MAX_MEMORY_SIZE = 4096
MAX_BASIC_BLOCKS = 8
MAX_INSTRUCTIONS_PER_BLOCK = 8
MAX_LOOP_ITERATIONS = 12


@dataclass
class _BBType:
    """Base class for basic block types in the CFG."""

    pass


@dataclass
class _ReturnBB(_BBType):
    """Basic block that returns."""

    pass


@dataclass
class _JumpBB(_BBType):
    """Basic block with unconditional jump."""

    target: IRBasicBlock


@dataclass
class _BranchBB(_BBType):
    """Basic block with conditional branch."""

    target1: IRBasicBlock
    target2: IRBasicBlock
    counter_addr: Optional[int] = None

    @property
    def has_back_edge(self) -> bool:
        return self.counter_addr is not None


class MemoryFuzzer:
    """Generates random Venom IR with memory operations using IRBasicBlock API."""

    def __init__(self):
        self.ctx = IRContext()
        self.function = None
        self.variable_counter = 0
        self.bb_counter = 0
        self.calldata_offset = MAX_MEMORY_SIZE
        self.available_vars = []
        self.allocated_memory_slots = set()

    def get_next_variable(self) -> IRVariable:
        """Generate a new unique variable."""
        self.variable_counter += 1
        var = IRVariable(f"v{self.variable_counter}")
        self.available_vars.append(var)
        return var

    def ensure_all_vars_have_values(self) -> None:
        """Ensure all available variables have values by using calldataload for unassigned ones."""
        assigned_vars = set()
        for bb in self.function.get_basic_blocks():
            for inst in bb.instructions:
                if inst.output:
                    assigned_vars.add(inst.output)

        entry_bb = self.function.entry
        unassigned_vars = [var for var in self.available_vars if var not in assigned_vars]

        for i, var in enumerate(unassigned_vars):
            inst = IRInstruction("calldataload", [IRLiteral(self.calldata_offset)], var)
            entry_bb.insert_instruction(inst, index=i)
            self.calldata_offset += 32

    def get_next_bb_label(self) -> IRLabel:
        """Generate a new unique basic block label."""
        self.bb_counter += 1
        return IRLabel(f"bb{self.bb_counter}")

    def get_random_variable(self, draw) -> IRVariable:
        """Get a random available variable or create a new one."""
        if self.available_vars and draw(st.booleans()):
            return draw(st.sampled_from(self.available_vars))
        else:
            return self.get_next_variable()

    def get_memory_address(self, draw) -> IRVariable | IRLiteral:
        """Get a memory address, biased towards interesting optimizer-relevant locations."""
        if self.available_vars and draw(st.booleans()):
            return draw(st.sampled_from(self.available_vars))

        if self.allocated_memory_slots and draw(st.booleans()):
            # bias towards addresses near existing allocations to create aliasing opportunities
            base_addr = draw(st.sampled_from(list(self.allocated_memory_slots)))

            offset = draw(st.integers(min_value=-32, max_value=32))
            if draw(st.booleans()):
                # snap to word boundaries for more interesting aliasing patterns
                offset = 0 if abs(offset) < 16 else (32 if offset > 0 else -32)

            addr = max(0, min(MAX_MEMORY_SIZE - 32, base_addr + offset))
        else:
            addr = draw(st.integers(min_value=0, max_value=MAX_MEMORY_SIZE - 32))

        self.allocated_memory_slots.add(addr)
        return IRLiteral(addr)


@st.composite
def copy_length(draw) -> int:
    """Generate a length suitable for a copy operation."""
    if draw(st.booleans()):
        # small lengths are more interesting for optimizer edge cases
        if draw(st.booleans()):
            return draw(
                st.sampled_from([1, 2, 4, 8, 16, 20, 24, 28, 31, 32, 33, 36, 40, 48, 64, 96])
            )
        else:
            return draw(st.integers(min_value=1, max_value=96))
    else:
        return draw(st.integers(min_value=97, max_value=1024))


@st.composite
def memory_instruction(draw, fuzzer: MemoryFuzzer, bb: IRBasicBlock) -> None:
    """Generate and append a memory instruction to current basic block."""
    op = draw(st.sampled_from(MEMORY_OPS))

    if op == "mload":
        addr = fuzzer.get_memory_address(draw)
        result_var = bb.append_instruction("mload", addr)
        fuzzer.available_vars.append(result_var)

    elif op == "mstore":
        if fuzzer.available_vars and draw(st.booleans()):
            value = draw(st.sampled_from(fuzzer.available_vars))
        else:
            value = IRLiteral(draw(st.integers(min_value=0, max_value=2**256 - 1)))
        addr = fuzzer.get_memory_address(draw)
        bb.append_instruction("mstore", value, addr)

    elif op == "mcopy":
        dest = fuzzer.get_memory_address(draw)
        src = fuzzer.get_memory_address(draw)
        length = draw(copy_length())
        bb.append_instruction("mcopy", dest, src, IRLiteral(length))

    else:
        raise ValueError("unreachable")


@st.composite
def control_flow_graph(draw, basic_blocks):
    """
    Generate a control flow graph that ensures:
    1. All blocks are reachable from entry
    2. No infinite loops (all loops terminate within 12 iterations)
    3. Proper use of jump and branch instructions
    """
    cfg: dict[IRBasicBlock, _BBType] = {}

    # last block is always a return block - guarantees all other blocks have forward targets
    cfg[basic_blocks[-1]] = _ReturnBB()

    # cache forward targets for each block for performance
    forward_targets = {}
    for i, bb in enumerate(basic_blocks):
        forward_targets[bb] = basic_blocks[i + 1 :]

    # create a spanning tree to ensure all blocks are reachable
    remaining_blocks = basic_blocks[1:]  # exclude entry block
    reachable_blocks = [basic_blocks[0]]

    while remaining_blocks:
        source = draw(st.sampled_from(reachable_blocks))
        target = draw(st.sampled_from(remaining_blocks))

        # target is now reachable, but it may not be in cfg yet
        reachable_blocks.append(target)
        remaining_blocks.remove(target)

        if draw(st.booleans()):
            cfg[source] = _JumpBB(target=target)
        else:
            other_target = draw(st.sampled_from(basic_blocks))
            cfg[source] = _BranchBB(target1=target, target2=other_target)

    # classify remaining blocks that were not handled during spanning
    # tree construction.
    loop_counter_addr = MAX_MEMORY_SIZE

    for bb in basic_blocks:
        if bb in cfg:
            continue

        edge_type = draw(st.sampled_from(["jump", "branch"]))

        if edge_type == "jump":
            target = draw(st.sampled_from(forward_targets[bb]))
            cfg[bb] = _JumpBB(target=target)
        else:  # branch
            target1 = draw(st.sampled_from(basic_blocks))
            target2 = draw(st.sampled_from(basic_blocks))

            is_back_edge1 = basic_blocks.index(target1) <= basic_blocks.index(bb)
            is_back_edge2 = basic_blocks.index(target2) <= basic_blocks.index(bb)

            if is_back_edge1 and is_back_edge2:
                # ensure at least one target provides forward progress
                target2 = draw(st.sampled_from(forward_targets[bb]))
                is_back_edge2 = False

            contains_back_edge = is_back_edge1 or is_back_edge2
            counter_addr = loop_counter_addr if contains_back_edge else None

            cfg[bb] = _BranchBB(target1=target1, target2=target2, counter_addr=counter_addr)

            if contains_back_edge:
                loop_counter_addr += 32

    return cfg


@st.composite
def precompile_call(draw, fuzzer: MemoryFuzzer, bb: IRBasicBlock) -> None:
    """Generate a call to a precompile that produces real output data."""

    precompile_addr = draw(st.sampled_from(list(PRECOMPILES.keys())))
    precompile_name = PRECOMPILES[precompile_addr]

    input_ofst = fuzzer.get_memory_address(draw)
    output_ofst = fuzzer.get_memory_address(draw)

    if precompile_name == "ecrecover":
        input_size = IRLiteral(128)  # v, r, s, hash
        output_size = IRLiteral(32)
    elif precompile_name == "sha256":
        input_size = IRLiteral(64)
        output_size = IRLiteral(32)
    elif precompile_name == "ripemd160":
        input_size = IRLiteral(64)
        output_size = IRLiteral(32)
    elif precompile_name == "identity":
        # identity copies min(input_size, output_size) bytes
        input_size = IRLiteral(draw(copy_length()))
        output_size = IRLiteral(draw(copy_length()))
    elif precompile_name == "modexp":
        input_size = IRLiteral(96)  # minimal: base_len, exp_len, mod_len
        output_size = IRLiteral(32)
    elif precompile_name == "ecadd":
        input_size = IRLiteral(128)  # two EC points (x1, y1, x2, y2)
        output_size = IRLiteral(64)
    elif precompile_name == "ecmul":
        input_size = IRLiteral(96)  # EC point (x, y) and scalar
        output_size = IRLiteral(64)
    elif precompile_name == "ecpairing":
        input_size = IRLiteral(192)  # minimal: one pair of G1 and G2 points
        output_size = IRLiteral(32)
    elif precompile_name == "blake2f":
        input_size = IRLiteral(213)  # blake2f requires specific input size
        output_size = IRLiteral(64)
    else:
        # unreachable
        raise Exception(f"Unknown precompile: {precompile_name}")

    gas = bb.append_instruction("gas")
    addr = IRLiteral(precompile_addr)

    bb.append_instruction("staticcall", gas, addr, input_ofst, input_size, output_ofst, output_size)


@st.composite
def basic_block_instructions(draw, fuzzer: MemoryFuzzer, bb: IRBasicBlock) -> None:
    """Generate instructions for a basic block."""
    num_instructions = draw(st.integers(min_value=1, max_value=MAX_INSTRUCTIONS_PER_BLOCK))

    for _ in range(num_instructions):
        inst_type = draw(st.sampled_from(["memory"] * 9 + ["precompile"]))

        if inst_type == "memory":
            draw(memory_instruction(fuzzer, bb))
        elif inst_type == "precompile":
            draw(precompile_call(fuzzer, bb))
        else:
            raise Exception("unreachable")


@st.composite
def venom_function_with_memory_ops(draw) -> IRContext:
    """Generate a complete Venom IR function using IRBasicBlock API."""
    fuzzer = MemoryFuzzer()

    func_name = IRLabel("_fuzz_function", is_symbol=True)
    fuzzer.function = IRFunction(func_name, fuzzer.ctx)
    fuzzer.ctx.functions[func_name] = fuzzer.function
    fuzzer.ctx.entry_function = fuzzer.function

    num_blocks = draw(st.integers(min_value=1, max_value=MAX_BASIC_BLOCKS))
    basic_blocks = []

    # clear default entry block
    fuzzer.function.clear_basic_blocks()

    for i in range(num_blocks):
        if i == 0:
            label = IRLabel("entry")
        else:
            label = fuzzer.get_next_bb_label()

        bb = IRBasicBlock(label, fuzzer.function)
        fuzzer.function.append_basic_block(bb)
        basic_blocks.append(bb)

    assert fuzzer.function.entry is basic_blocks[0]

    cfg = draw(control_flow_graph(basic_blocks))

    entry_block = basic_blocks[0]
    entry_block.append_instruction(
        "calldatacopy", IRLiteral(0), IRLiteral(0), IRLiteral(MAX_MEMORY_SIZE)
    )

    # extract loop counter addresses and initialize them
    counter_addrs = set()
    for bb_type in cfg.values():
        if isinstance(bb_type, _BranchBB) and bb_type.counter_addr is not None:
            addr = bb_type.counter_addr
            assert addr not in counter_addrs, f"Duplicate counter address {addr}"
            counter_addrs.add(addr)

    for addr in counter_addrs:
        entry_block.append_instruction("mstore", IRLiteral(0), IRLiteral(addr))

    for bb in basic_blocks:
        draw(basic_block_instructions(fuzzer, bb))

        bb_type = cfg[bb]

        if isinstance(bb_type, _ReturnBB):
            bb.append_instruction("return", IRLiteral(MAX_MEMORY_SIZE), IRLiteral(0))

        elif isinstance(bb_type, _JumpBB):
            bb.append_instruction("jmp", bb_type.target.label)

        elif isinstance(bb_type, _BranchBB):
            cond_var = fuzzer.get_random_variable(draw)
            # get bottom bit, for bias reasons
            cond_var = bb.append_instruction("and", cond_var, IRLiteral(1))

            if bb_type.has_back_edge:
                loop_counter_addr = IRLiteral(bb_type.counter_addr)

                counter = bb.append_instruction("mload", loop_counter_addr)
                incr_counter = bb.append_instruction("add", counter, IRLiteral(1))
                bb.append_instruction("mstore", incr_counter, loop_counter_addr)

                # exit loop when counter >= MAX_LOOP_ITERATIONS
                # (note we are guaranteed that second target provides forward
                # progress)
                max_iterations = IRLiteral(MAX_LOOP_ITERATIONS)
                # counter < iterbound
                counter_ok = bb.append_instruction("lt", counter, max_iterations)

                cond_var = bb.append_instruction("and", counter_ok, cond_var)

            bb.append_instruction("jnz", bb_type.target1.label, bb_type.target2.label, cond_var)

        else:
            raise Exception()  # unreachable

    fuzzer.ensure_all_vars_have_values()

    return fuzzer.ctx


class MemoryFuzzChecker:
    """A pluggable checker for memory passes using fuzzing."""

    def __init__(self, passes: list[type], post_passes: list[type] = None):
        self.passes = passes
        self.post_passes = post_passes or []

    def run_passes(self, ctx: IRContext) -> None:
        """
        Run optimization passes on the IR context.

        This method lets exceptions bubble up so Hypothesis can handle them properly.
        """
        optimized_ctx = ctx.copy()

        for fn in optimized_ctx.functions.values():
            ac = IRAnalysesCache(fn)
            for pass_class in self.passes:
                pass_obj = pass_class(ac, fn)
                pass_obj.run_pass()

            for pass_class in self.post_passes:
                pass_obj = pass_class(ac, fn)
                pass_obj.run_pass()


# Test with memory-related passes
@pytest.mark.fuzzing
@pytest.mark.parametrize(
    "pass_list",
    [
        # Test individual memory passes
        [LoadElimination],
        [DeadStoreElimination],
        [MemMergePass],
        # Test combinations
        [LoadElimination, DeadStoreElimination],
        [DeadStoreElimination, LoadElimination],
        [LoadElimination, MemMergePass],
    ],
)
@hp.given(ctx=venom_function_with_memory_ops())
@hp.settings(
    max_examples=100,
    suppress_health_check=(
        hp.HealthCheck.data_too_large,
        hp.HealthCheck.too_slow,
        hp.HealthCheck.filter_too_much,
    ),
    deadline=None,
)
def test_memory_passes_fuzzing(pass_list, ctx):
    """
    Property-based test for memory optimization passes.

    Tests that memory passes do not crash on complex IR.
    """
    hp.note(f"Testing passes: {[p.__name__ for p in pass_list]}")

    if hasattr(ctx, "functions") and ctx.functions:
        func = list(ctx.functions.values())[0]
        hp.note(f"Generated function with {func.num_basic_blocks} basic blocks")
        for bb in func.get_basic_blocks():
            hp.note(f"Block {bb.label.value}: {len(bb.instructions)} instructions")

    checker = MemoryFuzzChecker(pass_list)
    checker.run_passes(ctx)


def generate_sample_ir() -> IRContext:
    """Generate a sample IR for manual inspection."""
    ctx = venom_function_with_memory_ops().example()
    return ctx


if __name__ == "__main__":
    ctx = generate_sample_ir()

    func = list(ctx.functions.values())[0]
    print(f"Generated function with {func.num_basic_blocks} basic blocks:")
    print(func)

    checker = MemoryFuzzChecker([MemMergePass])
    checker.run_passes(ctx)
    print(ctx)

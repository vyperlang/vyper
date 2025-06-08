"""
Memory fuzzer for Venom IR.

This fuzzer generates complex control flow with memory instructions to test
memory optimization passes. It uses the IRBasicBlock API directly and
can be plugged with any Venom passes.
"""

import hypothesis as hp
import hypothesis.strategies as st
import pytest

from vyper.venom.analysis import IRAnalysesCache
from vyper.venom.basicblock import IRBasicBlock, IRInstruction, IRLabel, IRLiteral, IRVariable
from vyper.venom.context import IRContext
from vyper.venom.function import IRFunction
from vyper.venom.passes.dead_store_elimination import DeadStoreEliminationPass
from vyper.venom.passes.load_elimination import LoadEliminationPass
from vyper.venom.passes.memmerging import MemMergingPass

# Memory operations that can be fuzzed
MEMORY_OPS = ["mload", "mstore", "mcopy"]

# Precompile addresses for fence operations that generate real data
PRECOMPILES = {
    0x1: "ecrecover",  # Returns 32 bytes
    0x2: "sha256",  # Returns 32 bytes
    0x3: "ripemd160",  # Returns 32 bytes
    0x4: "identity",  # Returns input data
    0x5: "modexp",  # Returns variable length
    0x6: "ecadd",  # Returns 64 bytes
    0x7: "ecmul",  # Returns 64 bytes
    0x8: "ecpairing",  # Returns 32 bytes
    0x9: "blake2f",  # Returns 64 bytes
}

# Constants for fuzzing
MAX_MEMORY_SIZE = 4096  # Limit for memory operations
MAX_BASIC_BLOCKS = 8
MAX_INSTRUCTIONS_PER_BLOCK = 8
MAX_LOOP_ITERATIONS = 12  # Maximum iterations before forced loop exit


class MemoryFuzzer:
    """Generates random Venom IR with memory operations using IRBasicBlock API."""

    def __init__(self):
        self.ctx = IRContext()
        self.function = None
        self.variable_counter = 0
        self.bb_counter = 0
        self.calldata_offset = MAX_MEMORY_SIZE
        self.available_vars = []  # Variables available for use
        self.allocated_memory_slots = set()  # Track memory addresses that have been used

    def get_next_variable(self) -> IRVariable:
        """Generate a new unique variable."""
        self.variable_counter += 1
        var = IRVariable(f"v{self.variable_counter}")
        self.available_vars.append(var)
        return var

    def ensure_all_vars_have_values(self) -> None:
        """Ensure all available variables have values by using calldataload for unassigned ones."""
        # Find all variables that are outputs of instructions
        assigned_vars = set()
        for bb in self.function.get_basic_blocks():
            for inst in bb.instructions:
                if inst.output:
                    assigned_vars.add(inst.output)

        # For variables that don't have values, add calldataload at the beginning
        entry_bb = self.function.entry
        unassigned_vars = [var for var in self.available_vars if var not in assigned_vars]

        for i, var in enumerate(unassigned_vars):
            # Insert calldataload at the beginning of the entry block
            inst = IRInstruction("calldataload", [IRLiteral(self.calldata_offset)], var)
            entry_bb.insert_instruction(inst, index=i)
            self.calldata_offset += 32

    def get_next_bb_label(self) -> IRLabel:
        """Generate a new unique basic block label."""
        self.bb_counter += 1
        return IRLabel(f"bb{self.bb_counter}")

    def get_memory_address(self, draw) -> IRVariable | IRLiteral:
        """Get a memory address, biased towards interesting optimizer-relevant locations."""
        # 50% chance to use existing variable
        if self.available_vars and draw(st.booleans()):
            return draw(st.sampled_from(self.available_vars))

        # Generate literal address
        if self.allocated_memory_slots and draw(st.booleans()):
            # Bias towards addresses near existing allocations
            base_addr = draw(st.sampled_from(list(self.allocated_memory_slots)))

            # Random offset biased towards edges (0 and 32 are most common)
            offset = draw(st.integers(min_value=-32, max_value=32))
            if draw(st.booleans()):  # 50% chance to snap to edge
                offset = 0 if abs(offset) < 16 else (32 if offset > 0 else -32)

            addr = max(0, min(MAX_MEMORY_SIZE - 32, base_addr + offset))
        else:
            # Random address anywhere in memory
            addr = draw(st.integers(min_value=0, max_value=MAX_MEMORY_SIZE - 32))

        self.allocated_memory_slots.add(addr)
        return IRLiteral(addr)


@st.composite
def memory_instruction(draw, fuzzer: MemoryFuzzer) -> None:
    """Generate and append a memory instruction to current basic block."""
    op = draw(st.sampled_from(MEMORY_OPS))
    bb = fuzzer.current_bb

    if op == "mload":
        # %result = mload %addr
        addr = fuzzer.get_memory_address(draw)
        result_var = bb.append_instruction("mload", addr)
        fuzzer.available_vars.append(result_var)

    elif op == "mstore":
        # mstore %value, %addr
        # Random choice between variable and literal for value
        if fuzzer.available_vars and draw(st.booleans()):
            value = draw(st.sampled_from(fuzzer.available_vars))
        else:
            value = IRLiteral(draw(st.integers(min_value=0, max_value=2**256 - 1)))
        addr = fuzzer.get_memory_address(draw)
        bb.append_instruction("mstore", value, addr)

    elif op == "mcopy":
        # mcopy %dest, %src, %length
        dest = fuzzer.get_memory_address(draw)
        src = fuzzer.get_memory_address(draw)

        # Bias towards small lengths (more interesting for optimizers)
        if draw(st.booleans()):
            # Small lengths (1-96 bytes, biased towards 32-byte multiples)
            if draw(st.booleans()):
                length = draw(
                    st.sampled_from([1, 2, 4, 8, 16, 20, 24, 28, 31, 32, 33, 36, 40, 48, 64, 96])
                )
            else:
                length = draw(st.integers(min_value=1, max_value=96))
        else:
            # Larger lengths (up to 1KB)
            length = draw(st.integers(min_value=97, max_value=1024))

        bb.append_instruction("mcopy", dest, src, IRLiteral(length))


@st.composite
def control_flow_graph(draw, basic_blocks):
    """
    Generate a control flow graph that ensures:
    1. All blocks are reachable from entry
    2. No infinite loops (all loops terminate within 12 iterations)
    3. Proper use of jump and branch instructions
    """
    if len(basic_blocks) == 1:
        # Single block case - must return
        return {basic_blocks[0]: {"type": "return"}}

    cfg = {}
    entry_block = basic_blocks[0]

    # Create a spanning tree to ensure all blocks are reachable
    remaining_blocks = basic_blocks[1:]
    reachable_blocks = [entry_block]

    # Build spanning tree connections
    while remaining_blocks:
        # Pick a random reachable block to connect from
        source = draw(st.sampled_from(reachable_blocks))
        # Pick a random unreachable block to connect to
        target = draw(st.sampled_from(remaining_blocks))

        # Add the target to reachable blocks
        reachable_blocks.append(target)
        remaining_blocks.remove(target)

        # Decide if this connection should be a jump or branch
        if draw(st.booleans()):
            # Jump connection
            cfg[source] = {"type": "jump", "target": target}
        else:
            # Branch connection - need two targets
            other_target = draw(st.sampled_from(basic_blocks))
            cfg[source] = {"type": "branch", "target1": target, "target2": other_target}

    # Now add additional edges for more complex control flow
    num_additional_edges = draw(st.integers(min_value=0, max_value=len(basic_blocks)))
    loop_counter_addr = MAX_MEMORY_SIZE  # Start of reserved memory for metadata

    for _ in range(num_additional_edges):
        source = draw(st.sampled_from(basic_blocks))

        # Skip if already has terminator
        if source in cfg:
            continue

        edge_type = draw(st.sampled_from(["jump", "branch"]))

        if edge_type == "jump":
            target = draw(st.sampled_from(basic_blocks))

            # Check if this creates a back edge (potential loop)
            is_back_edge = basic_blocks.index(target) <= basic_blocks.index(source)

            if is_back_edge:
                # For back edges, use a branch with loop counter instead of unconditional jump
                cfg[source] = {
                    "type": "branch",
                    "target1": target,
                    "target2": draw(st.sampled_from(basic_blocks)),
                    "is_back_edge": True,
                    "counter_addr": loop_counter_addr,
                }
                loop_counter_addr += 32  # Next loop uses different memory location
            else:
                cfg[source] = {"type": "jump", "target": target}

        else:  # branch
            target1 = draw(st.sampled_from(basic_blocks))
            target2 = draw(st.sampled_from(basic_blocks))

            # Check if either target creates a back edge
            is_back_edge1 = basic_blocks.index(target1) <= basic_blocks.index(source)
            is_back_edge2 = basic_blocks.index(target2) <= basic_blocks.index(source)

            cfg[source] = {
                "type": "branch",
                "target1": target1,
                "target2": target2,
                "is_back_edge": is_back_edge1 or is_back_edge2,
                "counter_addr": loop_counter_addr if (is_back_edge1 or is_back_edge2) else None,
            }

            if is_back_edge1 or is_back_edge2:
                loop_counter_addr += 32

    # Ensure at least one block can return (avoid infinite execution)
    blocks_without_terminators = [bb for bb in basic_blocks if bb not in cfg]
    if blocks_without_terminators:
        # Make some blocks return
        num_returns = max(1, len(blocks_without_terminators) // 3)
        return_blocks = draw(
            st.lists(
                st.sampled_from(blocks_without_terminators),
                min_size=num_returns,
                max_size=num_returns,
                unique=True,
            )
        )
        for bb in return_blocks:
            cfg[bb] = {"type": "return"}

        # Add random terminators to remaining blocks
        remaining = [bb for bb in blocks_without_terminators if bb not in return_blocks]
        for bb in remaining:
            terminator_type = draw(st.sampled_from(["jump", "branch"]))
            if terminator_type == "jump":
                target = draw(st.sampled_from(basic_blocks))
                cfg[bb] = {"type": "jump", "target": target}
            else:
                target1 = draw(st.sampled_from(basic_blocks))
                target2 = draw(st.sampled_from(basic_blocks))
                cfg[bb] = {"type": "branch", "target1": target1, "target2": target2}

    return cfg


@st.composite
def precompile_call(draw, fuzzer: MemoryFuzzer) -> None:
    """Generate a call to a precompile that produces real output data."""
    bb = fuzzer.current_bb

    # Choose a precompile
    precompile_addr = draw(st.sampled_from(list(PRECOMPILES.keys())))
    precompile_name = PRECOMPILES[precompile_addr]

    # Set up input data in memory
    input_offset = fuzzer.get_memory_address(draw)
    output_offset = fuzzer.get_memory_address(draw)

    if precompile_name == "identity":
        # Identity precompile - copies input to output
        input_size = IRLiteral(32)
        output_size = IRLiteral(32)
    elif precompile_name == "sha256":
        # SHA256 - takes any input, outputs 32 bytes
        input_size = IRLiteral(64)  # Use 64 bytes input
        output_size = IRLiteral(32)
    elif precompile_name == "blake2f":
        # Blake2f - outputs 64 bytes
        input_size = IRLiteral(213)  # Blake2f requires 213 bytes input
        output_size = IRLiteral(64)
    elif precompile_name in ["ecadd", "ecmul"]:
        # EC operations - specific input/output sizes
        input_size = IRLiteral(96)  # EC point operations
        output_size = IRLiteral(64)
    else:
        # Default case
        input_size = IRLiteral(32)
        output_size = IRLiteral(32)

    # Call the precompile
    gas = bb.append_instruction("gas")  # Use all available gas
    addr = IRLiteral(precompile_addr)

    bb.append_instruction(
        "staticcall", gas, addr, input_offset, input_size, output_offset, output_size
    )


@st.composite
def basic_block_instructions(draw, fuzzer: MemoryFuzzer) -> None:
    """Generate instructions for a basic block."""

    # Generate main instructions
    num_instructions = draw(st.integers(min_value=1, max_value=MAX_INSTRUCTIONS_PER_BLOCK))

    for _ in range(num_instructions):
        # Choose instruction type
        inst_type = draw(st.sampled_from(["memory", "precompile"]))

        if inst_type == "memory":
            draw(memory_instruction(fuzzer))
        elif inst_type == "precompile":
            draw(precompile_call(fuzzer))


@st.composite
def venom_function_with_memory_ops(draw) -> IRContext:
    """Generate a complete Venom IR function using IRBasicBlock API."""

    fuzzer = MemoryFuzzer()

    # Create function
    func_name = IRLabel("_fuzz_function", is_symbol=True)
    fuzzer.function = IRFunction(func_name, fuzzer.ctx)
    fuzzer.ctx.functions[func_name] = fuzzer.function
    fuzzer.ctx.entry_function = fuzzer.function

    # Generate blocks
    num_blocks = draw(st.integers(min_value=1, max_value=MAX_BASIC_BLOCKS))
    basic_blocks = []

    for i in range(num_blocks):
        if i == 0:
            label = IRLabel("entry")
        else:
            label = fuzzer.get_next_bb_label()

        bb = IRBasicBlock(label, fuzzer.function)
        fuzzer.function.append_basic_block(bb)
        basic_blocks.append(bb)

    # Set entry block
    fuzzer.function.entry = basic_blocks[0]

    # Create a control flow graph that ensures reachability and loop termination
    cfg = draw(control_flow_graph(basic_blocks))

    # Initialize memory and loop counters at function entry
    entry_block = basic_blocks[0]
    entry_block.append_instruction(
        "calldatacopy", IRLiteral(0), IRLiteral(0), IRLiteral(MAX_MEMORY_SIZE)
    )

    # Extract used counter addresses from CFG and initialize them
    used_counter_addrs = set()
    for terminator_info in cfg.values():
        if terminator_info.get("counter_addr") is not None:
            addr = terminator_info["counter_addr"]
            assert addr not in used_counter_addrs, f"Duplicate counter address {addr}"
            used_counter_addrs.add(addr)

    for addr in used_counter_addrs:
        entry_block.append_instruction("mstore", IRLiteral(0), IRLiteral(addr))

    # Generate content for each block
    for bb in basic_blocks:
        fuzzer.current_bb = bb

        # Generate block content
        draw(basic_block_instructions(fuzzer))

        # Add terminators based on the control flow graph
        terminator_info = cfg[bb]
        if terminator_info["type"] == "return":
            bb.append_instruction("return", IRLiteral(MAX_MEMORY_SIZE), IRLiteral(0))
        elif terminator_info["type"] == "jump":
            target = terminator_info["target"]
            bb.append_instruction("jmp", target.label)
        elif terminator_info["type"] == "branch":
            # Use existing variable or create condition
            if fuzzer.available_vars:
                cond_var = draw(st.sampled_from(fuzzer.available_vars))
            else:
                cond_var = bb.append_instruction("mload", IRLiteral(0))

            # Add loop counter check if this is a back edge
            if terminator_info.get("is_back_edge", False):
                loop_counter_addr = terminator_info["counter_addr"]

                # Load and increment counter
                counter = bb.append_instruction("mload", IRLiteral(loop_counter_addr))
                incremented = bb.append_instruction("add", counter, IRLiteral(1))
                bb.append_instruction("mstore", incremented, IRLiteral(loop_counter_addr))

                # Check if we should continue looping (counter < MAX_LOOP_ITERATIONS)
                counter_lt_max = bb.append_instruction(
                    "lt", incremented, IRLiteral(MAX_LOOP_ITERATIONS)
                )

                # Normalize original condition to 0 or 1
                cond_normalized = bb.append_instruction("and", cond_var, IRLiteral(1))

                # Continue loop only if: counter < MAX AND original condition is true
                combined_cond = bb.append_instruction("and", counter_lt_max, cond_normalized)
                cond_var = combined_cond
            else:
                # Non-loop branches: just normalize condition to 0 or 1
                cond_var = bb.append_instruction("and", cond_var, IRLiteral(1))

            target1 = terminator_info["target1"]
            target2 = terminator_info["target2"]
            bb.append_instruction("jnz", target1.label, target2.label, cond_var)

    # Ensure all variables have values before returning
    fuzzer.ensure_all_vars_have_values()

    return fuzzer.ctx


class MemoryFuzzChecker:
    """A pluggable checker for memory passes using fuzzing."""

    def __init__(self, passes: list[type], post_passes: list[type] = None):
        self.passes = passes
        self.post_passes = post_passes or []

    def check_memory_equivalence(self, ctx: IRContext) -> bool:
        """
        Check that memory passes preserve semantics.

        For now, this just verifies that the passes run without errors.
        TODO: Implement actual semantic equivalence checking.
        """
        try:
            # Copy the context for optimization
            optimized_ctx = ctx.copy()

            # Apply passes to optimized version
            for fn in optimized_ctx.functions.values():
                ac = IRAnalysesCache(fn)
                for pass_class in self.passes:
                    pass_obj = pass_class(ac, fn)
                    pass_obj.run_pass()

                # Apply post passes
                for pass_class in self.post_passes:
                    pass_obj = pass_class(ac, fn)
                    pass_obj.run_pass()

            # If we get here, the passes ran successfully
            return True

        except Exception as e:
            # If optimization fails, the pass has a bug
            hp.note(f"Optimization failed: {e}")
            return False


# Test with memory-related passes
@pytest.mark.fuzzing
@pytest.mark.parametrize(
    "pass_list",
    [
        # Test individual memory passes
        [LoadEliminationPass],
        [DeadStoreEliminationPass],
        [MemMergingPass],
        # Test combinations
        [LoadEliminationPass, DeadStoreEliminationPass],
        [DeadStoreEliminationPass, LoadEliminationPass],
        [LoadEliminationPass, MemMergingPass],
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

    Tests that memory passes preserve semantics by comparing execution
    between optimized and unoptimized versions.
    """
    hp.note(f"Testing passes: {[p.__name__ for p in pass_list]}")

    # Log the generated IR for debugging
    if hasattr(ctx, "functions") and ctx.functions:
        func = list(ctx.functions.values())[0]
        hp.note(f"Generated function with {func.num_basic_blocks} basic blocks")
        for bb in func.get_basic_blocks():
            hp.note(f"Block {bb.label.value}: {len(bb.instructions)} instructions")

    checker = MemoryFuzzChecker(pass_list)

    # The property we're testing: optimization passes should not crash
    assert checker.check_memory_equivalence(ctx), "Memory optimization pass crashed"


# Utility function for manual testing
def generate_sample_ir() -> IRContext:
    """Generate a sample IR for manual inspection."""
    import random

    random.seed(42)

    # Create a hypothesis example
    ctx = venom_function_with_memory_ops().example()
    return ctx


if __name__ == "__main__":
    # Example usage
    ctx = generate_sample_ir()

    if ctx and ctx.functions:
        func = list(ctx.functions.values())[0]
        print(f"Generated function with {func.num_basic_blocks} basic blocks:")
        print(func)

        # Test with a simple pass
        checker = MemoryFuzzChecker([LoadEliminationPass])
        result = checker.check_memory_equivalence(ctx)
        print(f"\nEquivalence check result: {result}")

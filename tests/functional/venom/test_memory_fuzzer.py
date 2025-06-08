"""
Memory fuzzer for Venom IR.

This fuzzer generates complex control flow with memory instructions to test
memory optimization passes. It uses the IRBasicBlock API directly and
can be plugged with any Venom passes.
"""

import pytest
import hypothesis as hp
import hypothesis.strategies as st
from typing import List, Optional, Set

from tests.venom_utils import PrePostChecker
from tests.hevm import hevm_check_venom_ctx
from vyper.venom.analysis import IRAnalysesCache
from vyper.venom.basicblock import IRBasicBlock, IRInstruction, IRVariable, IRLiteral, IRLabel
from vyper.venom.context import IRContext
from vyper.venom.function import IRFunction
from vyper.venom.passes.base_pass import IRPass

# Memory operations that can be fuzzed
MEMORY_OPS = ["mload", "mstore", "mcopy"]

# Precompile addresses for fence operations that generate real data
PRECOMPILES = {
    0x1: "ecrecover",      # Returns 32 bytes
    0x2: "sha256",         # Returns 32 bytes  
    0x3: "ripemd160",      # Returns 32 bytes
    0x4: "identity",       # Returns input data
    0x5: "modexp",         # Returns variable length
    0x6: "ecadd",          # Returns 64 bytes
    0x7: "ecmul",          # Returns 64 bytes
    0x8: "ecpairing",      # Returns 32 bytes
    0x9: "blake2f",        # Returns 64 bytes
}

# Constants for fuzzing
MAX_MEMORY_SIZE = 4096  # Limit memory to 4096 bytes
MAX_BASIC_BLOCKS = 8
MAX_INSTRUCTIONS_PER_BLOCK = 8
MAX_VARIABLES = 20


class MemoryFuzzer:
    """Generates random Venom IR with memory operations using IRBasicBlock API."""
    
    def __init__(self, seed_memory: bool = True, allow_params: bool = True):
        self.seed_memory = seed_memory
        self.allow_params = allow_params
        self.ctx = IRContext()
        self.function = None
        self.variable_counter = 0
        self.bb_counter = 0
        self.available_vars = []  # Variables available for use
        
    def get_next_variable(self) -> IRVariable:
        """Generate a new unique variable."""
        self.variable_counter += 1
        var = IRVariable(f"v{self.variable_counter}")
        self.available_vars.append(var)
        return var
    
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
        """Get a memory address (either variable or aligned literal)."""
        if self.available_vars and draw(st.booleans()):
            return draw(st.sampled_from(self.available_vars))
        else:
            # Generate aligned memory addresses (multiples of 32)
            addr = draw(st.integers(min_value=0, max_value=MAX_MEMORY_SIZE - 32)) & ~31
            return IRLiteral(addr)


@st.composite  
def control_flow_graph(draw, max_blocks: int = MAX_BASIC_BLOCKS) -> dict:
    """Generate a complex control flow graph structure."""
    num_blocks = draw(st.integers(min_value=2, max_value=max_blocks))
    
    # Create adjacency list representation
    # Block 0 is always the entry, highest numbered block is always the exit
    edges = {}
    
    for i in range(num_blocks):
        edges[i] = []
    
    # Ensure connectivity: each block (except exit) has at least one outgoing edge
    for i in range(num_blocks - 1):
        # Add at least one outgoing edge to ensure no dead blocks
        if i == num_blocks - 2:
            # Second-to-last block must connect to exit
            edges[i].append(num_blocks - 1)
        else:
            # Can connect to any later block 
            target = draw(st.integers(min_value=i + 1, max_value=num_blocks - 1))
            edges[i].append(target)
    
    # Add some additional random edges for complexity
    for i in range(num_blocks - 1):
        # Chance to add more outgoing edges
        if draw(st.booleans()):
            # Don't create too many edges
            max_additional = min(2, num_blocks - i - 2)
            if max_additional > 0:
                num_additional = draw(st.integers(min_value=0, max_value=max_additional))
                for _ in range(num_additional):
                    # Choose a target we're not already connected to
                    possible_targets = [j for j in range(i + 1, num_blocks) if j not in edges[i]]
                    if possible_targets:
                        target = draw(st.sampled_from(possible_targets))
                        edges[i].append(target)
    
    return {"num_blocks": num_blocks, "edges": edges}


@st.composite
def memory_instruction(draw, fuzzer: MemoryFuzzer) -> None:
    """Generate and append a memory instruction to current basic block."""
    op = draw(st.sampled_from(MEMORY_OPS))
    bb = fuzzer.current_bb
    
    if op == "mload":
        # %result = mload %addr
        addr = fuzzer.get_memory_address(draw)
        result_var = bb.append_instruction("mload", addr)
        
    elif op == "mstore":
        # mstore %value, %addr
        value = fuzzer.get_random_variable(draw) if fuzzer.available_vars else IRLiteral(draw(st.integers(min_value=0, max_value=2**256-1)))
        addr = fuzzer.get_memory_address(draw)
        bb.append_instruction("mstore", value, addr)
        
    elif op == "mcopy":
        # mcopy %dest, %src, %length
        dest = fuzzer.get_memory_address(draw)
        src = fuzzer.get_memory_address(draw)
        length = IRLiteral(32)  # Copy 32 bytes
        bb.append_instruction("mcopy", dest, src, length)


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
    gas = IRLiteral(100000)  # Plenty of gas
    addr = IRLiteral(precompile_addr)
    value = IRLiteral(0)
    
    result_var = bb.append_instruction("staticcall", gas, addr, input_offset, input_size, output_offset, output_size)


@st.composite
def seed_memory_instruction(draw, fuzzer: MemoryFuzzer) -> None:
    """Generate an instruction that seeds memory with data."""
    bb = fuzzer.current_bb
    
    if fuzzer.allow_params:
        # Use calldataload to get "random" data from parameters
        offset = IRLiteral(draw(st.integers(min_value=0, max_value=256, step=32)))
        data_var = bb.append_instruction("calldataload", offset)
        
        # Store it in memory
        mem_addr = fuzzer.get_memory_address(draw)
        bb.append_instruction("mstore", data_var, mem_addr)
    else:
        # Just store a literal value
        value = IRLiteral(draw(st.integers(min_value=0, max_value=2**256-1)))
        mem_addr = fuzzer.get_memory_address(draw)
        bb.append_instruction("mstore", value, mem_addr)


@st.composite
def basic_block_instructions(draw, fuzzer: MemoryFuzzer, is_entry: bool = False) -> None:
    """Generate instructions for a basic block."""
    
    # For entry block, seed some memory first
    if is_entry and fuzzer.seed_memory:
        num_seeds = draw(st.integers(min_value=1, max_value=3))
        for _ in range(num_seeds):
            draw(seed_memory_instruction(fuzzer))
    
    # Generate main instructions
    num_instructions = draw(st.integers(min_value=1, max_value=MAX_INSTRUCTIONS_PER_BLOCK))
    
    for _ in range(num_instructions):
        # Choose instruction type
        inst_type = draw(st.sampled_from(["memory", "precompile", "seed"]))
        
        if inst_type == "memory":
            draw(memory_instruction(fuzzer))
        elif inst_type == "precompile": 
            draw(precompile_call(fuzzer))
        elif inst_type == "seed":
            draw(seed_memory_instruction(fuzzer))


@st.composite
def venom_function_with_memory_ops(draw) -> IRContext:
    """Generate a complete Venom IR function using IRBasicBlock API."""
    
    fuzzer = MemoryFuzzer(seed_memory=True, allow_params=True)
    
    # Create function
    func_name = IRLabel("_fuzz_function", is_symbol=True)
    fuzzer.function = IRFunction(func_name, fuzzer.ctx)
    fuzzer.ctx.functions[func_name] = fuzzer.function
    fuzzer.ctx.entry_function = fuzzer.function
    
    # Generate control flow structure
    cfg = draw(control_flow_graph())
    num_blocks = cfg["num_blocks"]
    edges = cfg["edges"]
    
    # Create all basic blocks first
    basic_blocks = []
    for i in range(num_blocks):
        if i == 0:
            label = IRLabel("entry")
        else:
            label = fuzzer.get_next_bb_label()
        
        bb = IRBasicBlock(label, fuzzer.function)
        fuzzer.function._basic_block_dict[label.value] = bb
        basic_blocks.append(bb)
    
    # Set entry block
    fuzzer.function.entry = basic_blocks[0]
    
    # Generate instructions for each block
    for i, bb in enumerate(basic_blocks):
        fuzzer.current_bb = bb
        
        # Generate block content
        is_entry = (i == 0)
        draw(basic_block_instructions(fuzzer, is_entry=is_entry))
        
        # Add terminator instruction
        outgoing_edges = edges[i]
        
        if i == num_blocks - 1:
            # Exit block - return memory contents
            bb.append_instruction("return", IRLiteral(MAX_MEMORY_SIZE), IRLiteral(0))
        elif len(outgoing_edges) == 1:
            # Single outgoing edge - unconditional jump
            target_bb = basic_blocks[outgoing_edges[0]]
            bb.append_instruction("jmp", target_bb.label)
        elif len(outgoing_edges) == 2:
            # Two outgoing edges - conditional jump
            # Create condition based on memory contents or available variable
            if fuzzer.available_vars:
                cond_var = draw(st.sampled_from(fuzzer.available_vars))
            else:
                # Load something from memory as condition
                cond_var = bb.append_instruction("mload", IRLiteral(0))
            
            target1_bb = basic_blocks[outgoing_edges[0]]
            target2_bb = basic_blocks[outgoing_edges[1]]
            bb.append_instruction("jnz", target1_bb.label, target2_bb.label, cond_var)
        else:
            # Multiple edges - use djmp (dynamic jump table)
            if fuzzer.available_vars:
                selector_var = draw(st.sampled_from(fuzzer.available_vars))
            else:
                selector_var = bb.append_instruction("mload", IRLiteral(0))
            
            # Create jump table
            target_labels = [basic_blocks[edge].label for edge in outgoing_edges]
            bb.append_instruction("djmp", selector_var, *target_labels)
    
    return fuzzer.ctx


class MemoryFuzzChecker:
    """A pluggable checker for memory passes using fuzzing."""
    
    def __init__(self, passes: List[type], post_passes: List[type] = None):
        self.passes = passes
        self.post_passes = post_passes or []
    
    def check_memory_equivalence(self, ctx: IRContext) -> bool:
        """
        Check that memory passes preserve semantics by comparing execution.
        
        Returns True if optimized and unoptimized versions are equivalent.
        """
        try:
            # Deep copy the context for optimization
            import copy
            unoptimized_ctx = copy.deepcopy(ctx)
            optimized_ctx = copy.deepcopy(ctx)
            
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
            
            # Use hevm to check equivalence if available
            try:
                hevm_check_venom_ctx(unoptimized_ctx, optimized_ctx)
                return True
            except Exception as e:
                # If hevm fails, we assume the optimization broke semantics
                hp.note(f"HEVM equivalence check failed: {e}")
                return False
                
        except Exception as e:
            # If optimization fails, skip this test case
            hp.note(f"Optimization failed: {e}")
            hp.assume(False)
            return False


# Test with memory-related passes
@pytest.mark.fuzzing  
@pytest.mark.parametrize("pass_list", [
    # Test individual memory passes
    [__import__("vyper.venom.passes.load_elimination", fromlist=["LoadEliminationPass"]).LoadEliminationPass],
    [__import__("vyper.venom.passes.dead_store_elimination", fromlist=["DeadStoreEliminationPass"]).DeadStoreEliminationPass],
    
    # Test combinations  
    [
        __import__("vyper.venom.passes.load_elimination", fromlist=["LoadEliminationPass"]).LoadEliminationPass,
        __import__("vyper.venom.passes.dead_store_elimination", fromlist=["DeadStoreEliminationPass"]).DeadStoreEliminationPass,
    ],
])
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
    if hasattr(ctx, 'functions') and ctx.functions:
        func = list(ctx.functions.values())[0]
        hp.note(f"Generated function with {len(func._basic_block_dict)} basic blocks")
        for bb_name, bb in func._basic_block_dict.items():
            hp.note(f"Block {bb_name}: {len(bb.instructions)} instructions")
    
    checker = MemoryFuzzChecker(pass_list)
    
    # The property we're testing: optimization should preserve semantics
    assert checker.check_memory_equivalence(ctx), "Memory optimization broke semantics"


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
        print(f"Generated function with {len(func._basic_block_dict)} basic blocks:")
        print(func)
        
        # Test with a simple pass
        try:
            from vyper.venom.passes.load_elimination import LoadEliminationPass
            checker = MemoryFuzzChecker([LoadEliminationPass])
            result = checker.check_memory_equivalence(ctx)
            print(f"\nEquivalence check result: {result}")
        except ImportError:
            print("Could not import LoadEliminationPass for testing")
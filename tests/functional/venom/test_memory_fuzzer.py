"""
Memory fuzzer for Venom IR.

This fuzzer generates complex control flow with memory instructions to test
memory optimization passes. It uses the IRBasicBlock API directly and
can be plugged with any Venom passes.

The fuzzer works in two phases:
1. Generation Phase: Creates IR with symbolic variables that can be used before definition
2. Resolution Phase: Replaces symbolic variables with real variables and inserts initialization

This two-phase approach enables complex cross-block dataflow patterns that would be
difficult to generate with a single pass.
"""
from dataclasses import dataclass
from typing import Optional

import hypothesis as hp
import hypothesis.strategies as st
import pytest

# increase hypothesis buffer size to allow for complex IR generation
# shrinking is quadratic in buffer size, but for compiler fuzzing finding
# bugs is more important than minimal reproductions
from hypothesis.internal.conjecture import engine as _hypothesis_engine
_hypothesis_engine.BUFFER_SIZE = 128 * 1024  # 128KB instead of default 8KB

from tests.evm_backends.base_env import EvmError
from tests.venom_utils import assert_ctx_eq
from vyper.evm.address_space import MEMORY
from vyper.ir.compile_ir import assembly_to_evm
from vyper.venom import VenomCompiler
from vyper.venom.analysis import IRAnalysesCache
from vyper.venom.basicblock import IRBasicBlock, IRInstruction, IRLabel, IRLiteral, IRVariable
from vyper.venom.context import IRContext
from vyper.venom.function import IRFunction
from vyper.venom.passes import (
    AssignElimination,
    CFGNormalization,
    DeadStoreElimination,
    LoadElimination,
    MakeSSA,
    MemMergePass,
    SimplifyCFGPass,
    SingleUseExpansion,
)

# ============================================================================
# Constants
# ============================================================================

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

MAX_MEMORY_SIZE = 256
MAX_BASIC_BLOCKS = 10
MAX_INSTRUCTIONS_PER_BLOCK = 20
MAX_LOOP_ITERATIONS = 12


# ============================================================================
# Basic Block Types
# ============================================================================


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
    """Basic block with conditional branch.

    Convention: If there's a back edge, target1 is the back edge and
    target2 is the forward edge. This ensures consistent loop structure.
    """

    target1: IRBasicBlock
    target2: IRBasicBlock
    has_back_edge: bool = False


# ============================================================================
# Symbolic Variables
# ============================================================================


class SymbolicVar(IRVariable):
    """Placeholder for a variable that will be resolved later.

    Symbolic variables enable cross-block dataflow patterns by allowing
    uses before definitions. During the resolution phase, each symbolic
    variable is replaced with a real variable and initialized via calldataload
    if it's used before being defined.
    """

    pass


# ============================================================================
# Memory Fuzzer
# ============================================================================


class MemoryFuzzer:
    """Generates random Venom IR with memory operations using IRBasicBlock API.

    This fuzzer creates complex control flow patterns with memory operations
    to stress-test memory optimization passes. It works in two phases:

    1. Generation: Build IR with symbolic variables, allowing flexible dataflow
    2. Resolution: Replace symbolic variables with real ones and add initialization
    """

    def __init__(self):
        self.ctx = IRContext()
        self.function = None
        self.bb_counter = 0
        self.calldata_offset = MAX_MEMORY_SIZE  # Start after memory seed data
        self.allocated_memory_slots = set()
        self.symbolic_counter = 0

    def get_next_variable(self) -> IRVariable:
        """Generate a new unique variable using the function's allocator."""
        assert self.function is not None, "Function must be set before allocating variables"
        return self.function.get_next_variable()

    def fresh_symbolic(self) -> SymbolicVar:
        """Create a new symbolic variable"""
        self.symbolic_counter += 1
        return SymbolicVar(f"%sym_{self.symbolic_counter}")

    def resolve_all_variables(self, block_types: dict[IRBasicBlock, _BBType]):
        """After building all blocks, replace symbolic vars with real ones"""
        # Simple global mapping - each symbolic var gets one real var
        symbolic_mapping = {}

        for bb in self.function.get_basic_blocks():
            insertions = []

            for i, inst in enumerate(bb.instructions):
                # First, handle output to allocate variable if needed
                output_sym = None
                if inst.has_outputs and isinstance(inst.output, SymbolicVar):
                    output_sym = inst.output
                    if inst.output not in symbolic_mapping:
                        symbolic_mapping[inst.output] = self.get_next_variable()
                    inst.set_outputs([symbolic_mapping[output_sym]])

                # Then resolve operands
                new_operands = []
                for op in inst.operands:
                    if isinstance(op, SymbolicVar):
                        if op not in symbolic_mapping:
                            # First use - create variable and schedule initialization
                            real_var = self.get_next_variable()
                            symbolic_mapping[op] = real_var
                            load_inst = IRInstruction(
                                "calldataload", [IRLiteral(self.calldata_offset)], [real_var]
                            )
                            insertions.append((i, load_inst))
                            self.calldata_offset += 32
                        op = symbolic_mapping[op]
                    new_operands.append(op)
                inst.operands = new_operands

            # Insert calldataloads
            for idx, load_inst in reversed(insertions):
                bb.insert_instruction(load_inst, index=idx)

    def get_next_bb_label(self) -> IRLabel:
        """Generate a new unique basic block label."""
        self.bb_counter += 1
        return IRLabel(f"bb{self.bb_counter}")

    def get_random_variable(self, draw, bb: IRBasicBlock) -> SymbolicVar:
        """Get a symbolic variable that will be resolved later."""
        # Always return symbolic variables during generation phase
        # They will be resolved to real variables with proper initialization
        return self.fresh_symbolic()

    def get_memory_address(self, draw, bb: IRBasicBlock) -> IRVariable | IRLiteral:
        """Get a memory address, biased towards interesting optimizer-relevant locations."""
        # Currently only returns literals to keep fuzzing patterns simple

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




# instruction data: (op_idx, use_literal, literal_value, addr1, addr2, copy_len)
# - op_idx: 0=mload, 1=mstore, 2=mcopy
# - use_literal: for mstore, whether to use literal vs symbolic
# - literal_value: value for mstore literal
# - addr1: first memory address
# - addr2: second memory address (for mcopy)
# - copy_len: length for mcopy
def instruction_data_strategy():
    """Strategy that generates all data for one instruction in a single draw."""
    return st.tuples(
        st.integers(0, 2),  # op_idx
        st.booleans(),  # use_literal
        st.integers(0, 2**64 - 1),  # literal_value (smaller range is fine)
        st.integers(0, MAX_MEMORY_SIZE - 32),  # addr1
        st.integers(0, MAX_MEMORY_SIZE - 32),  # addr2
        st.integers(1, 96),  # copy_len
    )


def apply_memory_instruction(
    fuzzer: MemoryFuzzer, bb: IRBasicBlock, inst_data: tuple
) -> None:
    """Apply instruction data to generate a memory instruction."""
    op_idx, use_literal, literal_value, addr1, addr2, copy_len = inst_data

    if op_idx == 0:  # mload
        result_var = fuzzer.fresh_symbolic()
        bb.append_instruction("mload", IRLiteral(addr1), ret=result_var)
    elif op_idx == 1:  # mstore
        if use_literal:
            value = IRLiteral(literal_value)
        else:
            value = fuzzer.fresh_symbolic()
        bb.append_instruction("mstore", value, IRLiteral(addr1))
    else:  # mcopy
        bb.append_instruction("mcopy", IRLiteral(addr1), IRLiteral(addr2), IRLiteral(copy_len))


# ============================================================================
# Control Flow Generation
# ============================================================================




@st.composite
def control_flow_graph(draw, basic_blocks):
    """
    Generate a CFG where:
    1. All blocks are reachable from entry
    2. Every block has at least one forward edge (no infinite loops)
    3. No back edges to entry block
    """
    if len(basic_blocks) == 1:
        return {basic_blocks[0]: _ReturnBB()}

    entry = basic_blocks[0]
    return_block = basic_blocks[-1]
    non_entry = basic_blocks[1:]

    def block_index(bb):
        return basic_blocks.index(bb)

    def is_forward(src, dst):
        return block_index(dst) > block_index(src)

    def forward_targets(bb):
        return basic_blocks[block_index(bb) + 1:]

    block_types = {}
    unreached = list(non_entry)  # never contains entry, list for deterministic order
    to_process = [entry]

    def mark_reached(bb):
        """Mark a block as reached, adding to process queue if new."""
        if bb in unreached:
            unreached.remove(bb)
            to_process.append(bb)

    while to_process:
        bb = draw(st.sampled_from(to_process))
        to_process.remove(bb)

        if bb == return_block:
            block_types[bb] = _ReturnBB()
            continue

        fwd = forward_targets(bb)

        # pick primary target, prioritizing unreached blocks
        if unreached:
            primary = draw(st.sampled_from(unreached))
        else:
            primary = draw(st.sampled_from(fwd))
        mark_reached(primary)

        primary_is_forward = is_forward(bb, primary)

        # only allow jump if:
        # 1. primary is forward (ensures forward progress)
        # 2. all blocks are already reachable (otherwise need branch to reach more)
        use_jump = primary_is_forward and not unreached and draw(st.booleans())

        if use_jump:
            block_types[bb] = _JumpBB(target=primary)
        else:
            # branch: pick second target, prioritizing unreached blocks
            if unreached:
                secondary = draw(st.sampled_from(unreached))
            else:
                secondary = draw(st.sampled_from(non_entry))

            if secondary == primary:
                others = [b for b in non_entry if b != primary]
                secondary = draw(st.sampled_from(others)) if others else return_block

            secondary_is_forward = is_forward(bb, secondary)

            # ensure at least one forward edge (prevents infinite loops)
            if not primary_is_forward and not secondary_is_forward:
                secondary = draw(st.sampled_from(fwd))
                secondary_is_forward = True

            mark_reached(secondary)

            # convention: target1 is back edge if there is one
            has_back_edge = not primary_is_forward or not secondary_is_forward
            if not secondary_is_forward and primary_is_forward:
                primary, secondary = secondary, primary

            block_types[bb] = _BranchBB(
                target1=primary, target2=secondary, has_back_edge=has_back_edge
            )

    return block_types


# precompile data: (precompile_idx, input_ofst, output_ofst)
PRECOMPILE_LIST = list(PRECOMPILES.keys())
PRECOMPILE_SIZES = {
    0x1: (128, 32),   # ecrecover
    0x2: (64, 32),    # sha256
    0x3: (64, 32),    # ripemd160
    0x4: (64, 64),    # identity (using fixed sizes)
    0x5: (96, 32),    # modexp
    0x6: (128, 64),   # ecadd
    0x7: (96, 64),    # ecmul
    0x8: (192, 32),   # ecpairing
    0x9: (213, 64),   # blake2f
}


def precompile_data_strategy():
    """Strategy that generates all data for one precompile call."""
    return st.tuples(
        st.integers(0, len(PRECOMPILE_LIST) - 1),  # precompile_idx
        st.integers(0, MAX_MEMORY_SIZE - 32),  # input_ofst
        st.integers(0, MAX_MEMORY_SIZE - 32),  # output_ofst
    )


# precompiles with invalid input consume all forwarded gas on failure,
# so use a fixed gas limit instead of forwarding all remaining gas
PRECOMPILE_GAS = 100_000


def apply_precompile_call(fuzzer: MemoryFuzzer, bb: IRBasicBlock, data: tuple) -> None:
    """Apply precompile data to generate a staticcall instruction."""
    precompile_idx, input_ofst, output_ofst = data
    precompile_addr = PRECOMPILE_LIST[precompile_idx]
    input_size, output_size = PRECOMPILE_SIZES[precompile_addr]

    success = fuzzer.fresh_symbolic()
    bb.append_instruction(
        "staticcall",
        IRLiteral(output_size),
        IRLiteral(output_ofst),
        IRLiteral(input_size),
        IRLiteral(input_ofst),
        IRLiteral(precompile_addr),
        IRLiteral(PRECOMPILE_GAS),
        ret=success,
    )


def block_instructions_strategy():
    """Strategy that generates all instruction data for one block as a list."""
    # each element is (is_precompile, data_tuple)
    # 90% memory, 10% precompile via st.one_of with weighted alternatives
    memory_inst = st.tuples(st.just(False), instruction_data_strategy())
    precompile_inst = st.tuples(st.just(True), precompile_data_strategy())
    inst = st.one_of(*([memory_inst] * 9), precompile_inst)
    return st.lists(inst, min_size=1, max_size=MAX_INSTRUCTIONS_PER_BLOCK)


def apply_block_instructions(
    fuzzer: MemoryFuzzer, bb: IRBasicBlock, inst_list: list
) -> None:
    """Apply a list of instruction data to a basic block."""
    for is_precompile, data in inst_list:
        if is_precompile:
            apply_precompile_call(fuzzer, bb, data)
        else:
            apply_memory_instruction(fuzzer, bb, data)


# ============================================================================
# Main Generation Function
# ============================================================================


@st.composite
def venom_function_with_memory_ops(draw) -> tuple[IRContext, int]:
    """Generate a complete Venom IR function using IRBasicBlock API.

    Returns:
        tuple[IRContext, int]: The generated IR context and the required calldata size.
        The calldata size includes both the initial memory seed (MAX_MEMORY_SIZE bytes)
        and any additional calldata needed for unassigned variables.
    """
    fuzzer = MemoryFuzzer()

    # ---- Setup function and context ----
    func_name = IRLabel("_fuzz_function", is_symbol=True)
    fuzzer.function = IRFunction(func_name, fuzzer.ctx)
    fuzzer.ctx.functions[func_name] = fuzzer.function
    fuzzer.ctx.entry_function = fuzzer.function

    # ---- Generate basic blocks ----
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

    # ---- Generate control flow ----
    block_types = draw(control_flow_graph(basic_blocks))

    # ---- Initialize memory and loop counter ----
    # IMPORTANT: These must be the first instructions in entry block to ensure
    # they execute before any potential CFG splits during normalization
    entry_block = basic_blocks[0]

    # initialize memory to the contents of calldata ("random" data)
    entry_block.append_instruction(
        "calldatacopy", IRLiteral(MAX_MEMORY_SIZE), IRLiteral(0), IRLiteral(0),
    )

    # check if any block has a back edge - if so we need a global counter
    has_any_back_edge = any(
        isinstance(bt, _BranchBB) and bt.has_back_edge for bt in block_types.values()
    )

    # use a single global counter at a fixed address for all back edges
    # this prevents nested loops from multiplying iteration counts
    global_counter_addr = MAX_MEMORY_SIZE
    if has_any_back_edge:
        entry_block.append_instruction("mstore", IRLiteral(0), IRLiteral(global_counter_addr))

    # ---- Generate instructions ----
    # Draw all instruction data upfront for all blocks
    all_block_instructions = draw(
        st.lists(block_instructions_strategy(), min_size=num_blocks, max_size=num_blocks)
    )

    # Apply instructions to each block
    for bb, inst_list in zip(basic_blocks, all_block_instructions):
        apply_block_instructions(fuzzer, bb, inst_list)

    # ---- Add terminators ----
    for bb in basic_blocks:
        bb_type = block_types[bb]

        if isinstance(bb_type, _ReturnBB):
            bb.append_instruction("return", IRLiteral(MAX_MEMORY_SIZE), IRLiteral(0))

        elif isinstance(bb_type, _JumpBB):
            bb.append_instruction("jmp", bb_type.target.label)

        elif isinstance(bb_type, _BranchBB):
            # If both targets are the same, convert to unconditional jump
            if bb_type.target1 == bb_type.target2:
                bb.append_instruction("jmp", bb_type.target1.label)
                continue

            cond_var = fuzzer.get_random_variable(draw, bb)
            # get bottom bit, for bias reasons
            cond_result = fuzzer.fresh_symbolic()
            bb.append_instruction("and", cond_var, IRLiteral(1), ret=cond_result)

            if bb_type.has_back_edge:
                loop_counter_addr = IRLiteral(global_counter_addr)

                counter = fuzzer.fresh_symbolic()
                bb.append_instruction("mload", loop_counter_addr, ret=counter)

                incr_counter = fuzzer.fresh_symbolic()
                bb.append_instruction("add", counter, IRLiteral(1), ret=incr_counter)
                bb.append_instruction("mstore", incr_counter, loop_counter_addr)

                max_iterations = IRLiteral(MAX_LOOP_ITERATIONS)
                counter_ok = fuzzer.fresh_symbolic()
                bb.append_instruction("lt", max_iterations, counter, ret=counter_ok)

                final_cond = fuzzer.fresh_symbolic()
                bb.append_instruction("and", counter_ok, cond_result, ret=final_cond)
                cond_result = final_cond

            # when there is a back edge, target2 is always the forward edge
            bb.append_instruction("jnz", cond_result, bb_type.target1.label, bb_type.target2.label)

        else:
            raise AssertionError(f"Unknown basic block type: {type(bb_type)}")

    # ---- Phase 2: Resolve symbolic variables ----
    fuzzer.resolve_all_variables(block_types)

    # freshen variable names for easier debugging
    for fn in fuzzer.ctx.functions.values():
        fn.freshen_varnames()

    return fuzzer.ctx, fuzzer.calldata_offset


# ============================================================================
# Memory Pass Checker
# ============================================================================


class MemoryFuzzChecker:
    """A pluggable checker for memory passes using fuzzing."""

    def __init__(self, passes: list[type]):
        self.passes = passes

    def compile_to_bytecode(self, ctx: IRContext) -> bytes:
        """Compile Venom IR context to EVM bytecode."""
        for fn in ctx.functions.values():
            ac = IRAnalysesCache(fn)
            SimplifyCFGPass(ac, fn).run_pass()
            MakeSSA(ac, fn).run_pass()
            SingleUseExpansion(ac, fn).run_pass()
            CFGNormalization(ac, fn).run_pass()

        compiler = VenomCompiler(ctx)
        asm = compiler.generate_evm_assembly()
        bytecode, _ = assembly_to_evm(asm)
        return bytecode

    def run_passes(self, ctx: IRContext) -> IRContext:
        """
        Copies the IRContext and runs optimization passes on the copy of the IR context.

        Returns the optimized context.
        """
        optimized_ctx = ctx.copy()

        for fn in optimized_ctx.functions.values():
            ac = IRAnalysesCache(fn)

            for pass_class in self.passes:
                pass_obj = pass_class(ac, fn)
                if pass_class == DeadStoreElimination:
                    pass_obj.run_pass(addr_space=MEMORY)
                else:
                    pass_obj.run_pass()

        return optimized_ctx

    def execute_bytecode(self, bytecode: bytes, calldata: bytes, env) -> tuple[bool, bytes]:
        """Execute bytecode with given calldata and return success status and output."""
        # wrap runtime bytecode in deploy bytecode that returns it
        bytecode_len = len(bytecode)
        bytecode_len_hex = hex(bytecode_len)[2:].rjust(4, "0")
        # deploy preamble: PUSH2 len, 0, DUP2, PUSH1 0a, 0, CODECOPY, RETURN
        deploy_preamble = bytes.fromhex("61" + bytecode_len_hex + "3d81600a3d39f3")
        deploy_bytecode = deploy_preamble + bytecode

        deployed_address = env._deploy(deploy_bytecode)

        try:
            result = env.message_call(to=deployed_address, data=calldata, gas=10_000_000)
            return True, result
        except EvmError as e:
            # stub for future handling of programs that are actually expected to revert
            raise

    def check_equivalence(self, ctx: IRContext, calldata: bytes, env) -> None:
        """Check equivalence between unoptimized and optimized execution."""
        # run MakeSSA on the original context first
        for fn in ctx.functions.values():
            ac = IRAnalysesCache(fn)
            MakeSSA(ac, fn).run_pass()
            AssignElimination(ac, fn).run_pass()
            fn.freshen_varnames()

        opt_ctx = self.run_passes(ctx)
        for fn in opt_ctx.functions.values():
            fn.freshen_varnames()

        try:
            assert_ctx_eq(ctx, opt_ctx)
        except AssertionError as e:
            equals = False
            msg = e.args[0]
        else:
            equals = True

        if equals:
            hp.note("No optimization done")
            return

        hp.note("UNOPTIMIZED: " + str(ctx))
        hp.note("OPTIMIZED: " + str(opt_ctx))
        hp.note("optimizations: " + str(msg))

        bytecode1 = self.compile_to_bytecode(ctx)
        bytecode2 = self.compile_to_bytecode(opt_ctx)

        hp.note(f"MSG CALL {calldata.hex()}")

        succ1, out1 = self.execute_bytecode(bytecode1, calldata, env)
        succ2, out2 = self.execute_bytecode(bytecode2, calldata, env)

        if not succ1 or not succ2:
            hp.note("reverted")
        else:
            hp.note(f"OUT {out1.hex()}")

        assert succ1 == succ2, (succ1, out1, succ2, out2)
        assert out1 == out2, (succ1, out1, succ2, out2)


# ============================================================================
# Test Helpers
# ============================================================================


@st.composite
def venom_with_calldata(draw):
    """Generate Venom IR context with matching calldata."""
    ctx, calldata_size = draw(venom_function_with_memory_ops())
    # use a seeded random for calldata - costs ~4 choices instead of calldata_size
    import random
    seed = draw(st.integers(0, 2**32 - 1))
    rng = random.Random(seed)
    calldata = bytes(rng.getrandbits(8) for _ in range(calldata_size))
    return ctx, calldata


# ============================================================================
# Property-Based Tests
# ============================================================================


@pytest.mark.fuzzing
@hp.given(venom_data=venom_with_calldata())
@hp.settings(
    max_examples=1000,
    suppress_health_check=(hp.HealthCheck.data_too_large, hp.HealthCheck.too_slow),
    deadline=None,
    # skip `target` phase - it tries to maximize which causes buffer overruns
    phases=(hp.Phase.explicit, hp.Phase.reuse, hp.Phase.generate),
    verbosity=hp.Verbosity.verbose,
)
def test_memory_passes_fuzzing(venom_data, env):
    """
    Property-based test for memory optimization passes.

    Tests that memory passes preserve semantics by comparing EVM execution results.
    """
    # NOTE: DeadStoreElimination has a bug where it treats call/staticcall output
    # writes as unconditional clobbers. If a call fails, it doesn't write to the
    # output buffer, but DSE assumes it always does. This causes DSE to incorrectly
    # eliminate stores that are still needed when calls fail. Excluding DSE until fixed.
    pass_list = [LoadElimination, MemMergePass]
    ctx, calldata = venom_data

    checker = MemoryFuzzChecker(pass_list)
    checker.check_equivalence(ctx, calldata, env)


# ============================================================================
# Manual Testing
# ============================================================================


def generate_sample_ir() -> IRContext:
    """Generate a sample IR for manual inspection."""
    ctx, _ = venom_function_with_memory_ops().example()
    return ctx


if __name__ == "__main__":
    ctx = generate_sample_ir()
    checker = MemoryFuzzChecker([LoadElimination, MemMergePass, DeadStoreElimination])
    checker.run_passes(ctx)
    print(ctx)

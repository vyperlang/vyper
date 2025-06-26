"""
Memory fuzzer for Venom IR.

This fuzzer generates complex control flow with memory instructions to test
memory optimization passes. It uses the IRBasicBlock API directly and
can be plugged with any Venom passes.
"""
from collections import defaultdict
from dataclasses import dataclass
from typing import Optional

import hypothesis as hp
import hypothesis.strategies as st
import pytest

from tests.evm_backends.base_env import EvmError
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
MAX_BASIC_BLOCKS = 50
MAX_INSTRUCTIONS_PER_BLOCK = 50
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
    def needs_loop_counter(self) -> bool:
        return self.counter_addr is not None


class SymbolicVar(IRVariable):
    """Placeholder for a variable that will be resolved later"""

    pass


class MemoryFuzzer:
    """Generates random Venom IR with memory operations using IRBasicBlock API."""

    def __init__(self):
        self.ctx = IRContext()
        self.function = None
        self.bb_counter = 0
        self.calldata_offset = MAX_MEMORY_SIZE
        self.allocated_memory_slots = set()
        # symbolic variable tracking
        self.symbolic_counter = 0

    def get_next_variable(self) -> IRVariable:
        """Generate a new unique variable using the function's allocator."""
        assert self.function is not None, "Function must be set before allocating variables"
        return self.function.get_next_variable()

    def fresh_symbolic(self) -> SymbolicVar:
        """Create a new symbolic variable"""
        self.symbolic_counter += 1
        return SymbolicVar(f"%sym_{self.symbolic_counter}")

    def resolve_all_variables(self, cfg: dict[IRBasicBlock, _BBType]):
        """After building all blocks, replace symbolic vars with real ones"""
        # Simple global mapping - each symbolic var gets one real var
        symbolic_mapping = {}

        for bb in self.function.get_basic_blocks():
            insertions = []

            for i, inst in enumerate(bb.instructions):
                # First, handle output to allocate variable if needed
                output_sym = None
                if inst.output and isinstance(inst.output, SymbolicVar):
                    output_sym = inst.output
                    if inst.output not in symbolic_mapping:
                        symbolic_mapping[inst.output] = self.get_next_variable()
                    inst.output = symbolic_mapping[inst.output]

                # Then resolve operands
                new_operands = []
                for op in inst.operands:
                    if isinstance(op, SymbolicVar):
                        if op not in symbolic_mapping:
                            # First use - create variable and schedule initialization
                            real_var = self.get_next_variable()
                            symbolic_mapping[op] = real_var
                            load_inst = IRInstruction(
                                "calldataload", [IRLiteral(self.calldata_offset)], real_var
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
        # For now, only return literals to avoid cross-block availability issues
        # TODO: Once we have proper availability tracking, we can use variables again

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
        addr = fuzzer.get_memory_address(draw, bb)
        result_var = fuzzer.fresh_symbolic()
        bb.append_instruction("mload", addr, ret=result_var)

    elif op == "mstore":
        # Use either a symbolic variable or a literal
        if draw(st.booleans()):
            value = fuzzer.get_random_variable(draw, bb)
        else:
            value = IRLiteral(draw(st.integers(min_value=0, max_value=2**256 - 1)))
        addr = fuzzer.get_memory_address(draw, bb)
        bb.append_instruction("mstore", value, addr)

    elif op == "mcopy":
        dest = fuzzer.get_memory_address(draw, bb)
        src = fuzzer.get_memory_address(draw, bb)
        length = draw(copy_length())
        bb.append_instruction("mcopy", dest, src, IRLiteral(length))

    else:
        raise Exception("unreachable")


@st.composite
def control_flow_graph(draw, basic_blocks):
    """
    Generate a control flow graph that ensures:
    1. All blocks are reachable from entry
    2. No infinite loops (all loops terminate within 12 iterations)
    3. Proper use of jump and branch instructions
    4. No back edges to entry block
    """
    cfg: dict[IRBasicBlock, _BBType] = {}

    # last block is always a return block - guarantees all other blocks have forward targets
    cfg[basic_blocks[-1]] = _ReturnBB()

    # cache forward targets for each block for performance
    forward_targets = {}
    for i, bb in enumerate(basic_blocks):
        forward_targets[bb] = basic_blocks[i + 1 :]

    # All blocks except entry (to prevent back edges to entry)
    non_entry_blocks = basic_blocks[1:]

    # create a spanning tree to ensure all blocks are reachable
    remaining_blocks = basic_blocks[1:]  # exclude entry block
    reachable_blocks = [basic_blocks[0]]

    while remaining_blocks:
        source = draw(st.sampled_from(reachable_blocks))

        # we have already visited it
        if source in cfg:
            continue

        target = draw(st.sampled_from(remaining_blocks))

        # target is now reachable, but it may not be in cfg yet
        reachable_blocks.append(target)
        remaining_blocks.remove(target)

        if draw(st.booleans()):
            cfg[source] = _JumpBB(target=target)
        else:
            # For branches, allow any block as the other target except entry
            # (target is already guaranteed to be forward)
            other_target = draw(st.sampled_from(non_entry_blocks))

            is_back_edge = basic_blocks.index(other_target) <= basic_blocks.index(source)
            # counter_addr = loop_counter_addr if is_back_edge else None

            # if other_target is the back edge, swap so back edge is always target1
            if is_back_edge:
                other_target, target = target, other_target
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
            # Choose targets, but never allow entry as a target
            target1 = draw(st.sampled_from(non_entry_blocks))
            target2 = draw(st.sampled_from(non_entry_blocks))

            is_back_edge1 = basic_blocks.index(target1) <= basic_blocks.index(bb)
            is_back_edge2 = basic_blocks.index(target2) <= basic_blocks.index(bb)

            if is_back_edge1 and is_back_edge2:
                # ensure at least one target provides forward progress
                target2 = draw(st.sampled_from(forward_targets[bb]))
                is_back_edge2 = False

            contains_back_edge = is_back_edge1 or is_back_edge2

            # swap targets so target2 is always a forward edge
            if is_back_edge2 and not is_back_edge1:
                target1, target2 = target2, target1

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

    input_ofst = fuzzer.get_memory_address(draw, bb)
    output_ofst = fuzzer.get_memory_address(draw, bb)

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

    gas = fuzzer.fresh_symbolic()
    bb.append_instruction("gas", ret=gas)
    addr = IRLiteral(precompile_addr)

    success = fuzzer.fresh_symbolic()
    bb.append_instruction(
        "staticcall", gas, addr, input_ofst, input_size, output_ofst, output_size, ret=success
    )


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
def venom_function_with_memory_ops(draw) -> tuple[IRContext, int]:
    """Generate a complete Venom IR function using IRBasicBlock API.

    Returns:
        tuple[IRContext, int]: The generated IR context and the required calldata size.
        The calldata size includes both the initial memory seed (MAX_MEMORY_SIZE bytes)
        and any additional calldata needed for unassigned variables.
    """
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

    # generate instructions for each block
    for bb in basic_blocks:
        draw(basic_block_instructions(fuzzer, bb))

    # add terminators
    for bb in basic_blocks:
        bb_type = cfg[bb]

        if isinstance(bb_type, _ReturnBB):
            bb.append_instruction("return", IRLiteral(MAX_MEMORY_SIZE), IRLiteral(0))

        elif isinstance(bb_type, _JumpBB):
            bb.append_instruction("jmp", bb_type.target.label)

        elif isinstance(bb_type, _BranchBB):
            cond_var = fuzzer.get_random_variable(draw, bb)
            # get bottom bit, for bias reasons
            cond_result = fuzzer.fresh_symbolic()
            bb.append_instruction("and", cond_var, IRLiteral(1), ret=cond_result)

            if bb_type.needs_loop_counter:
                loop_counter_addr = IRLiteral(bb_type.counter_addr)

                counter = fuzzer.fresh_symbolic()
                bb.append_instruction("mload", loop_counter_addr, ret=counter)

                incr_counter = fuzzer.fresh_symbolic()
                bb.append_instruction("add", counter, IRLiteral(1), ret=incr_counter)
                bb.append_instruction("mstore", incr_counter, loop_counter_addr)

                max_iterations = IRLiteral(MAX_LOOP_ITERATIONS)
                counter_ok = fuzzer.fresh_symbolic()
                bb.append_instruction("lt", counter, max_iterations, ret=counter_ok)

                final_cond = fuzzer.fresh_symbolic()
                bb.append_instruction("and", counter_ok, cond_result, ret=final_cond)
                cond_result = final_cond

            # when there is a back edge, target2 is always the forward edge
            bb.append_instruction("jnz", cond_result, bb_type.target1.label, bb_type.target2.label)

        else:
            raise Exception()  # unreachable

    # resolve all symbolic variables to real ones
    fuzzer.resolve_all_variables(cfg)

    # freshen variable names for easier debugging
    for fn in fuzzer.ctx.functions.values():
        fn.freshen_varnames()

    return fuzzer.ctx, fuzzer.calldata_offset


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
            fn.freshen_varnames()

        hp.note(str(ctx))

        compiler = VenomCompiler([ctx])
        asm = compiler.generate_evm()
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
            result = env.message_call(to=deployed_address, data=calldata)
            return True, result
        except EvmError:
            return False, b""

    def check_equivalence(self, ctx: IRContext, calldata: bytes, env) -> None:
        """Check equivalence between unoptimized and optimized execution."""
        # run MakeSSA on the original context first
        for fn in ctx.functions.values():
            ac = IRAnalysesCache(fn)
            MakeSSA(ac, fn).run_pass()
            AssignElimination(ac, fn).run_pass()
        hp.note("UNOPTIMIZED: " + str(ctx))

        opt_ctx = self.run_passes(ctx)
        hp.note("OPTIMIZED: " + str(opt_ctx))

        bytecode1 = self.compile_to_bytecode(ctx)
        bytecode2 = self.compile_to_bytecode(opt_ctx)

        succ1, out1 = self.execute_bytecode(bytecode1, calldata, env)
        succ2, out2 = self.execute_bytecode(bytecode2, calldata, env)

        assert succ1 == succ2, (succ1, out1, succ2, out2)
        assert out1 == out2, (succ1, out1, succ2, out2)


@st.composite
def venom_with_calldata(draw):
    """Generate Venom IR context with matching calldata."""
    ctx, calldata_size = draw(venom_function_with_memory_ops())
    calldata = draw(st.binary(min_size=calldata_size, max_size=calldata_size))
    return ctx, calldata


# Test with memory-related passes
@pytest.mark.fuzzing
# @pytest.mark.parametrize(
#    "pass_list",
#    [
#        # Test individual memory passes
#        [MemMergePass],
#        [LoadElimination],
#        [DeadStoreElimination],
#        # Test combinations
#        [LoadElimination, DeadStoreElimination],
#        [DeadStoreElimination, LoadElimination],
#        [LoadElimination, MemMergePass],
#    ],
# )
@hp.given(venom_data=venom_with_calldata())
@hp.settings(
    max_examples=50,
    suppress_health_check=(hp.HealthCheck.data_too_large, hp.HealthCheck.too_slow),
    deadline=None,
    phases=(
        hp.Phase.explicit,
        hp.Phase.reuse,
        hp.Phase.generate,
        hp.Phase.target,
        # Phase.shrink,  # can force long waiting for examples
    ),
    # verbosity=hp.Verbosity.debug,
)
def test_memory_passes_fuzzing(venom_data, env):
    """
    Property-based test for memory optimization passes.

    Tests that memory passes preserve semantics by comparing EVM execution results.
    """
    pass_list = [MemMergePass]
    ctx, calldata = venom_data

    hp.note(f"Testing passes: {[p.__name__ for p in pass_list]}")

    func = list(ctx.functions.values())[0]
    hp.note(f"Generated function with {func.num_basic_blocks} basic blocks")
    hp.note(f"Calldata size: {len(calldata)} bytes")
    hp.note(str(ctx))

    checker = MemoryFuzzChecker(pass_list)
    checker.check_equivalence(ctx, calldata, env)


def generate_sample_ir() -> IRContext:
    """Generate a sample IR for manual inspection."""
    ctx, _ = venom_function_with_memory_ops().example()
    return ctx


if __name__ == "__main__":
    ctx = generate_sample_ir()

    # func = list(ctx.functions.values())[0]
    # print(func)

    checker = MemoryFuzzChecker([MemMergePass])
    checker.run_passes(ctx)
    print(ctx)
    bytecode = checker.compile_to_bytecode(ctx)
    print(bytecode.hex())

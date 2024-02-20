from typing import Any

from vyper.ir.compile_ir import PUSH, DataHeader, RuntimeHeader, optimize_assembly
from vyper.utils import MemoryPositions, OrderedSet
from vyper.venom.analysis import calculate_cfg, calculate_liveness, input_vars_from
from vyper.venom.basicblock import (
    IRBasicBlock,
    IRInstruction,
    IRLabel,
    IRLiteral,
    IROperand,
    IRVariable,
    MemType,
)
from vyper.venom.function import IRFunction
from vyper.venom.passes.normalization import NormalizationPass
from vyper.venom.stack_model import StackModel

# instructions which map one-to-one from venom to EVM
_ONE_TO_ONE_INSTRUCTIONS = frozenset(
    [
        "revert",
        "coinbase",
        "calldatasize",
        "calldatacopy",
        "calldataload",
        "gas",
        "gasprice",
        "gaslimit",
        "address",
        "origin",
        "number",
        "extcodesize",
        "extcodehash",
        "returndatasize",
        "returndatacopy",
        "callvalue",
        "selfbalance",
        "sload",
        "sstore",
        "mload",
        "mstore",
        "timestamp",
        "caller",
        "selfdestruct",
        "signextend",
        "stop",
        "shr",
        "shl",
        "and",
        "xor",
        "or",
        "add",
        "sub",
        "mul",
        "div",
        "mod",
        "exp",
        "eq",
        "iszero",
        "not",
        "lg",
        "lt",
        "slt",
        "sgt",
    ]
)

_REVERT_POSTAMBLE = ["_sym___revert", "JUMPDEST", *PUSH(0), "DUP1", "REVERT"]


# TODO: "assembly" gets into the recursion due to how the original
# IR was structured recursively in regards with the deploy instruction.
# There, recursing into the deploy instruction was by design, and
# made it easier to make the assembly generated "recursive" (i.e.
# instructions being lists of instructions). We don't have this restriction
# anymore, so we can probably refactor this to be iterative in coordination
# with the assembler. My suggestion is to let this be for now, and we can
# refactor it later when we are finished phasing out the old IR.
class VenomCompiler:
    ctxs: list[IRFunction]
    label_counter = 0
    visited_instructions: OrderedSet  # {IRInstruction}
    visited_basicblocks: OrderedSet  # {IRBasicBlock}

    def __init__(self, ctxs: list[IRFunction]):
        self.ctxs = ctxs
        self.label_counter = 0
        self.visited_instructions = OrderedSet()
        self.visited_basicblocks = OrderedSet()

    def generate_evm(self, no_optimize: bool = False) -> list[str]:
        self.visited_instructions = OrderedSet()
        self.visited_basicblocks = OrderedSet()
        self.label_counter = 0

        asm: list[Any] = []
        top_asm = asm

        # Before emitting the assembly, we need to make sure that the
        # CFG is normalized. Calling calculate_cfg() will denormalize IR (reset)
        # so it should not be called after calling NormalizationPass.run_pass().
        # Liveness is then computed for the normalized IR, and we can proceed to
        # assembly generation.
        # This is a side-effect of how dynamic jumps are temporarily being used
        # to support the O(1) dispatcher. -> look into calculate_cfg()
        for ctx in self.ctxs:
            calculate_cfg(ctx)
            NormalizationPass.run_pass(ctx)
            calculate_liveness(ctx)

            assert ctx.normalized, "Non-normalized CFG!"

            self._generate_evm_for_basicblock_r(asm, ctx.basic_blocks[0], StackModel())

            # TODO make this property on IRFunction
            if ctx.immutables_len is not None and ctx.ctor_mem_size is not None:
                while asm[-1] != "JUMPDEST":
                    asm.pop()
                asm.extend(
                    ["_sym_subcode_size", "_sym_runtime_begin", "_mem_deploy_start", "CODECOPY"]
                )
                asm.extend(["_OFST", "_sym_subcode_size", ctx.immutables_len])  # stack: len
                asm.extend(["_mem_deploy_start"])  # stack: len mem_ofst
                asm.extend(["RETURN"])
                asm.extend(_REVERT_POSTAMBLE)
                runtime_asm = [
                    RuntimeHeader("_sym_runtime_begin", ctx.ctor_mem_size, ctx.immutables_len)
                ]
                asm.append(runtime_asm)
                asm = runtime_asm
            else:
                asm.extend(_REVERT_POSTAMBLE)

            # Append data segment
            data_segments: dict = dict()
            for inst in ctx.data_segment:
                if inst.opcode == "dbname":
                    label = inst.operands[0].value
                    data_segments[label] = [DataHeader(f"_sym_{label}")]
                elif inst.opcode == "db":
                    data_segments[label].append(f"_sym_{inst.operands[0].value}")

            asm.extend(list(data_segments.values()))

        if no_optimize is False:
            optimize_assembly(top_asm)

        return top_asm

    def _stack_reorder(
        self, assembly: list, stack: StackModel, _stack_ops: OrderedSet[IRVariable]
    ) -> None:
        # make a list so we can index it
        stack_ops = [x for x in _stack_ops.keys()]
        stack_ops_count = len(_stack_ops)

        for i in range(stack_ops_count):
            op = stack_ops[i]
            final_stack_depth = -(stack_ops_count - i - 1)
            depth = stack.get_depth(op)  # type: ignore

            if depth == final_stack_depth:
                continue

            self.swap(assembly, stack, depth)
            self.swap(assembly, stack, final_stack_depth)

    def _emit_input_operands(
        self, assembly: list, inst: IRInstruction, ops: list[IROperand], stack: StackModel
    ) -> None:
        # PRE: we already have all the items on the stack that have
        # been scheduled to be killed. now it's just a matter of emitting
        # SWAPs, DUPs and PUSHes until we match the `ops` argument

        # dumb heuristic: if the top of stack is not wanted here, swap
        # it with something that is wanted
        if ops and stack.height > 0 and stack.peek(0) not in ops:
            for op in ops:
                if isinstance(op, IRVariable) and op not in inst.dup_requirements:
                    self.swap_op(assembly, stack, op)
                    break

        emitted_ops = OrderedSet[IROperand]()
        for op in ops:
            if isinstance(op, IRLabel):
                # invoke emits the actual instruction itself so we don't need to emit it here
                # but we need to add it to the stack map
                if inst.opcode != "invoke":
                    assembly.append(f"_sym_{op.value}")
                stack.push(op)
                continue

            if isinstance(op, IRLiteral):
                assembly.extend([*PUSH(op.value)])
                stack.push(op)
                continue

            if op in inst.dup_requirements:
                self.dup_op(assembly, stack, op)

            if op in emitted_ops:
                self.dup_op(assembly, stack, op)

            # REVIEW: this seems like it can be reordered across volatile
            # boundaries (which includes memory fences). maybe just
            # remove it entirely at this point
            if isinstance(op, IRVariable) and op.mem_type == MemType.MEMORY:
                assembly.extend([*PUSH(op.mem_addr)])
                assembly.append("MLOAD")

            emitted_ops.add(op)

    def _generate_evm_for_basicblock_r(
        self, asm: list, basicblock: IRBasicBlock, stack: StackModel
    ) -> None:
        if basicblock in self.visited_basicblocks:
            return
        self.visited_basicblocks.add(basicblock)

        # assembly entry point into the block
        asm.append(f"_sym_{basicblock.label}")
        asm.append("JUMPDEST")

        self.clean_stack_from_cfg_in(asm, basicblock, stack)

        for inst in basicblock.instructions:
            asm = self._generate_evm_for_instruction(asm, inst, stack)

        for bb in basicblock.cfg_out:
            self._generate_evm_for_basicblock_r(asm, bb, stack.copy())

    # pop values from stack at entry to bb
    # note this produces the same result(!) no matter which basic block
    # we enter from in the CFG.
    def clean_stack_from_cfg_in(
        self, asm: list, basicblock: IRBasicBlock, stack: StackModel
    ) -> None:
        if len(basicblock.cfg_in) == 0:
            return

        to_pop = OrderedSet[IRVariable]()
        for in_bb in basicblock.cfg_in:
            # inputs is the input variables we need from in_bb
            inputs = input_vars_from(in_bb, basicblock)

            # layout is the output stack layout for in_bb (which works
            # for all possible cfg_outs from the in_bb).
            layout = in_bb.out_vars

            # pop all the stack items which in_bb produced which we don't need.
            to_pop |= layout.difference(inputs)

        for var in to_pop:
            depth = stack.get_depth(var)
            # don't pop phantom phi inputs
            if depth is StackModel.NOT_IN_STACK:
                continue

            if depth != 0:
                stack.swap(depth)
            self.pop(asm, stack)

    def _generate_evm_for_instruction(
        self, assembly: list, inst: IRInstruction, stack: StackModel
    ) -> list[str]:
        opcode = inst.opcode

        #
        # generate EVM for op
        #

        # Step 1: Apply instruction special stack manipulations

        if opcode in ["jmp", "djmp", "jnz", "invoke"]:
            operands = inst.get_non_label_operands()
        elif opcode == "alloca":
            operands = inst.operands[1:2]
        elif opcode == "iload":
            operands = []
        elif opcode == "istore":
            operands = inst.operands[0:1]
        elif opcode == "log":
            log_topic_count = inst.operands[0].value
            assert log_topic_count in [0, 1, 2, 3, 4], "Invalid topic count"
            operands = inst.operands[1:]
        else:
            operands = inst.operands

        if opcode == "phi":
            ret = inst.get_outputs()[0]
            phi1, phi2 = inst.get_inputs()
            depth = stack.get_phi_depth(phi1, phi2)
            # collapse the arguments to the phi node in the stack.
            # example, for `%56 = %label1 %13 %label2 %14`, we will
            # find an instance of %13 *or* %14 in the stack and replace it with %56.
            to_be_replaced = stack.peek(depth)
            if to_be_replaced in inst.dup_requirements:
                # %13/%14 is still live(!), so we make a copy of it
                self.dup(assembly, stack, depth)
                stack.poke(0, ret)
            else:
                stack.poke(depth, ret)
            return assembly

        # Step 2: Emit instruction's input operands
        self._emit_input_operands(assembly, inst, operands, stack)

        # Step 3: Reorder stack
        if opcode in ["jnz", "djmp", "jmp"]:
            # prepare stack for jump into another basic block
            assert inst.parent and isinstance(inst.parent.cfg_out, OrderedSet)
            b = next(iter(inst.parent.cfg_out))
            target_stack = input_vars_from(inst.parent, b)
            # TODO optimize stack reordering at entry and exit from basic blocks
            self._stack_reorder(assembly, stack, target_stack)

        # final step to get the inputs to this instruction ordered
        # correctly on the stack
        self._stack_reorder(assembly, stack, OrderedSet(operands))

        # some instructions (i.e. invoke) need to do stack manipulations
        # with the stack model containing the return value(s), so we fiddle
        # with the stack model beforehand.

        # Step 4: Push instruction's return value to stack
        stack.pop(len(operands))
        if inst.output is not None:
            stack.push(inst.output)

        # Step 5: Emit the EVM instruction(s)
        if opcode in _ONE_TO_ONE_INSTRUCTIONS:
            assembly.append(opcode.upper())
        elif opcode == "alloca":
            pass
        elif opcode == "param":
            pass
        elif opcode == "store":
            pass
        elif opcode == "dbname":
            pass
        elif opcode in ["codecopy", "dloadbytes"]:
            assembly.append("CODECOPY")
        elif opcode == "jnz":
            # jump if not zero
            if_nonzero_label = inst.operands[1]
            if_zero_label = inst.operands[2]
            assembly.append(f"_sym_{if_nonzero_label.value}")
            assembly.append("JUMPI")

            # make sure the if_zero_label will be optimized out
            # assert if_zero_label == next(iter(inst.parent.cfg_out)).label

            assembly.append(f"_sym_{if_zero_label.value}")
            assembly.append("JUMP")

        elif opcode == "jmp":
            assert isinstance(inst.operands[0], IRLabel)
            assembly.append(f"_sym_{inst.operands[0].value}")
            assembly.append("JUMP")
        elif opcode == "djmp":
            assert isinstance(inst.operands[0], IRVariable)
            assembly.append("JUMP")
        elif opcode == "gt":
            assembly.append("GT")
        elif opcode == "lt":
            assembly.append("LT")
        elif opcode == "invoke":
            target = inst.operands[0]
            assert isinstance(target, IRLabel), "invoke target must be a label"
            assembly.extend(
                [
                    f"_sym_label_ret_{self.label_counter}",
                    f"_sym_{target.value}",
                    "JUMP",
                    f"_sym_label_ret_{self.label_counter}",
                    "JUMPDEST",
                ]
            )
            self.label_counter += 1
            if stack.height > 0 and stack.peek(0) in inst.dup_requirements:
                self.pop(assembly, stack)
        elif opcode == "call":
            assembly.append("CALL")
        elif opcode == "staticcall":
            assembly.append("STATICCALL")
        elif opcode == "ret":
            assembly.append("JUMP")
        elif opcode == "return":
            assembly.append("RETURN")
        elif opcode == "phi":
            pass
        elif opcode == "sha3":
            assembly.append("SHA3")
        elif opcode == "sha3_64":
            assembly.extend(
                [
                    *PUSH(MemoryPositions.FREE_VAR_SPACE2),
                    "MSTORE",
                    *PUSH(MemoryPositions.FREE_VAR_SPACE),
                    "MSTORE",
                    *PUSH(64),
                    *PUSH(MemoryPositions.FREE_VAR_SPACE),
                    "SHA3",
                ]
            )
        elif opcode == "ceil32":
            assembly.extend([*PUSH(31), "ADD", *PUSH(31), "NOT", "AND"])
        elif opcode == "assert":
            assembly.extend(["ISZERO", "_sym___revert", "JUMPI"])
        elif opcode == "iload":
            loc = inst.operands[0].value
            assembly.extend(["_OFST", "_mem_deploy_end", loc, "MLOAD"])
        elif opcode == "istore":
            loc = inst.operands[1].value
            assembly.extend(["_OFST", "_mem_deploy_end", loc, "MSTORE"])
        elif opcode == "log":
            assembly.extend([f"LOG{log_topic_count}"])
        else:
            raise Exception(f"Unknown opcode: {opcode}")

        # Step 6: Emit instructions output operands (if any)
        if inst.output is not None:
            assert isinstance(inst.output, IRVariable), "Return value must be a variable"
            if inst.output.mem_type == MemType.MEMORY:
                assembly.extend([*PUSH(inst.output.mem_addr)])

        return assembly

    def pop(self, assembly, stack, num=1):
        stack.pop(num)
        assembly.extend(["POP"] * num)

    def swap(self, assembly, stack, depth):
        if depth == 0:
            return
        stack.swap(depth)
        assembly.append(_evm_swap_for(depth))

    def dup(self, assembly, stack, depth):
        stack.dup(depth)
        assembly.append(_evm_dup_for(depth))

    def swap_op(self, assembly, stack, op):
        self.swap(assembly, stack, stack.get_depth(op))

    def dup_op(self, assembly, stack, op):
        self.dup(assembly, stack, stack.get_depth(op))


def _evm_swap_for(depth: int) -> str:
    swap_idx = -depth
    assert 1 <= swap_idx <= 16, "Unsupported swap depth"
    return f"SWAP{swap_idx}"


def _evm_dup_for(depth: int) -> str:
    dup_idx = 1 - depth
    assert 1 <= dup_idx <= 16, "Unsupported dup depth"
    return f"DUP{dup_idx}"

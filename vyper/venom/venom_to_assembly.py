from vyper.ir.compile_ir import PUSH, DataHeader, RuntimeHeader, optimize_assembly
from vyper.utils import MemoryPositions, OrderedSet
from vyper.venom.basicblock import (
    IRBasicBlock,
    IRInstruction,
    IRLabel,
    IRValueBase,
    IRVariable,
    MemType,
)
from vyper.venom.bb_optimizer import calculate_cfg, calculate_liveness
from vyper.venom.function import IRFunction
from vyper.venom.stack_model import StackModel

# binary instructions which are commutative
_COMMUTATIVE_INSTRUCTIONS = frozenset(["add", "mul", "and", "or", "xor", "eq"])

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
        "lg",
        "lt",
        "slt",
        "sgt",
        "log0",
        "log1",
        "log2",
        "log3",
        "log4",
    ]
)


# figure out which variables we need to emit DUPs for for this
# instruction (because they are still live after the instruction
def _compute_dup_requirements(ctx: IRFunction) -> None:
    for bb in ctx.basic_blocks:
        _compute_dup_requirements_bb(bb)


def _compute_dup_requirements_bb(bb: IRBasicBlock) -> None:
    # the most recent instruction which used this variable
    most_recent_use_of = dict()

    for inst in bb.instructions:
        # reset dup_requirements
        inst.dup_requirements = OrderedSet()

        for op in inst.get_inputs():
            # the variable is still live at `inst`, so we look
            # back to `most_recent_use_of[op]` and add to its
            # dup requirements.
            if op in most_recent_use_of:
                target = most_recent_use_of[op]
                target.dup_requirements.add(op)

            most_recent_use_of[op] = inst

            if op in bb.out_vars:
                inst.dup_requirements.add(op)


# REVIEW: "assembly" gets into the recursion due to how the original
# IR was structured recursively in regards with the deploy instruction.
# There, recursing into the deploy instruction was by design, and
# made it easier to make the assembly generated "recursive" (i.e.
# instructions being lists of instructions). We don't have this restriction
# anymore, so we can probably refactor this to be iterative in coordination
# with the assembler. My suggestion is to let this be for now, and we can
# refactor it later when we are finished phasing out the old IR.
class VenomCompiler:
    ctx: IRFunction
    label_counter = 0
    visited_instructions = None  # {IRInstruction}
    visited_basicblocks = None  # {IRBasicBlock}

    def __init__(self, ctx: IRFunction):
        self.ctx = ctx
        self.label_counter = 0
        self.visited_instructions = None
        self.visited_basicblocks = None

    def generate_evm(self, no_optimize: bool = False) -> list[str]:
        self.visited_instructions = OrderedSet()
        self.visited_basicblocks = OrderedSet()
        self.label_counter = 0

        stack = StackModel()
        asm = []

        calculate_cfg(self.ctx)

        # REVIEW: calculate_liveness and compute_dup_requirements are really
        # related, maybe they can be combined somehow. or maybe they should go
        # into vyper/venom/analysis.py
        calculate_liveness(self.ctx)
        _compute_dup_requirements(self.ctx)

        self._generate_evm_for_basicblock_r(asm, self.ctx.basic_blocks[0], stack)

        # Append postambles
        revert_postamble = ["_sym___revert", "JUMPDEST", *PUSH(0), "DUP1", "REVERT"]
        runtime = None
        if isinstance(asm[-1], list) and isinstance(asm[-1][0], RuntimeHeader):
            runtime = asm.pop()

        asm.extend(revert_postamble)
        if runtime:
            runtime.extend(revert_postamble)
            asm.append(runtime)

        # Append data segment
        data_segments = {}
        for inst in self.ctx.data_segment:
            if inst.opcode == "dbname":
                label = inst.operands[0].value
                data_segments[label] = [DataHeader(f"_sym_{label}")]
            elif inst.opcode == "db":
                data_segments[label].append(f"_sym_{inst.operands[0].value}")

        extent_point = asm if not isinstance(asm[-1], list) else asm[-1]
        extent_point.extend([data_segments[label] for label in data_segments])

        if no_optimize is False:
            optimize_assembly(asm)

        return asm

    def _stack_reorder(
        self,
        assembly: list,
        stack: StackModel,
        stack_ops: OrderedSet[IRVariable],
        commutative: bool = False,
    ) -> None:
        # make a list so we can index it
        stack_ops = [x for x in stack_ops]
        stack_ops_count = len(stack_ops)

        if commutative:
            depth = stack.get_depth(stack_ops[0])
            # TODO: Apply commutative knowledge to optimize stack
            # if depth == 0:
            #     stack_ops = list(reversed(stack_ops))

        for i in range(stack_ops_count):
            op = stack_ops[i]
            final_stack_depth = -(stack_ops_count - i - 1)
            depth = stack.get_depth(op)

            if depth == final_stack_depth:
                continue

            self.swap(assembly, stack, depth)
            self.swap(assembly, stack, final_stack_depth)

    def _get_commutative_alternative(self, depth: int) -> int:
        if depth == 0:
            return -1
        elif depth == -1:
            return 0
        assert False, f"Invalid depth {depth}"

    def _emit_input_operands(
        self,
        assembly: list,
        inst: IRInstruction,
        ops: list[IRValueBase],
        stack: StackModel,
    ):
        # PRE: we already have all the items on the stack that have
        # been scheduled to be killed. now it's just a matter of emitting
        # SWAPs, DUPs and PUSHes until we match the `ops` argument

        # dumb heuristic: if the top of stack is not wanted here, swap
        # it with something that is wanted
        if ops and stack.stack and stack.stack[-1] not in ops:
            for op in ops:
                if isinstance(op, IRVariable) and op not in inst.dup_requirements:
                    self.swap_op(assembly, stack, op)
                    break

        emitted_ops = OrderedSet()
        for op in ops:
            if isinstance(op, IRLabel):
                # invoke emits the actual instruction itself so we don't need to emit it here
                # but we need to add it to the stack map
                if inst.opcode != "invoke":
                    assembly.append(f"_sym_{op.value}")
                stack.push(op)
                continue

            if op.is_literal:
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
    ):
        if basicblock in self.visited_basicblocks:
            return
        self.visited_basicblocks.add(basicblock)

        asm.append(f"_sym_{basicblock.label}")
        asm.append("JUMPDEST")

        for inst in basicblock.instructions:
            asm = self._generate_evm_for_instruction(asm, inst, stack)

        for bb in basicblock.cfg_out:
            self._generate_evm_for_basicblock_r(asm, bb, stack.copy())

    def _generate_evm_for_instruction(
        self, assembly: list, inst: IRInstruction, stack: StackModel
    ) -> list[str]:
        opcode = inst.opcode

        #
        # generate EVM for op
        #

        # Step 1: Apply instruction special stack manipulations

        if opcode in ["jmp", "jnz", "invoke"]:
            operands = inst.get_non_label_operands()
        elif opcode == "alloca":
            operands = inst.operands[1:2]
        elif opcode == "iload":
            operands = []
        elif opcode == "istore":
            operands = inst.operands[0:1]
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
        if opcode in ["jnz", "jmp"]:
            assert isinstance(inst.parent.cfg_out, OrderedSet)
            b = next(iter(inst.parent.cfg_out))
            target_stack = b.in_vars_from(inst.parent)
            # REVIEW: this seems like it generates bad code, because
            # the next _stack_reorder will undo the changes to the stack.
            self._stack_reorder(assembly, stack, target_stack)

        is_commutative = opcode in _COMMUTATIVE_INSTRUCTIONS
        self._stack_reorder(assembly, stack, operands, is_commutative)

        # some instructions (i.e. invoke) need to do stack manipulations
        # with the stack model containing the return value(s), so we fiddle
        # with the stack model beforehand.

        # Step 4: Push instruction's return value to stack
        stack.pop(len(operands))
        if inst.ret is not None:
            stack.push(inst.ret)

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
            assembly.append(f"_sym_{inst.operands[1].value}")
            assembly.append("JUMPI")
        elif opcode == "jmp":
            if isinstance(inst.operands[0], IRLabel):
                assembly.append(f"_sym_{inst.operands[0].value}")
                assembly.append("JUMP")
            else:
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
            if stack.get_height() > 0 and stack.peek(0) in inst.dup_requirements:
                stack.pop()
                assembly.append("POP")
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
        elif opcode == "deploy":
            memsize = inst.operands[0].value
            padding = inst.operands[2].value
            # TODO: fix this by removing deploy opcode altogether me move emition to ir translation
            while assembly[-1] != "JUMPDEST":
                assembly.pop()
            assembly.extend(
                ["_sym_subcode_size", "_sym_runtime_begin", "_mem_deploy_start", "CODECOPY"]
            )
            assembly.extend(["_OFST", "_sym_subcode_size", padding])  # stack: len
            assembly.extend(["_mem_deploy_start"])  # stack: len mem_ofst
            assembly.extend(["RETURN"])
            assembly.append([RuntimeHeader("_sym_runtime_begin", memsize, padding)])
            assembly = assembly[-1]
        elif opcode == "iload":
            loc = inst.operands[0].value
            assembly.extend(["_OFST", "_mem_deploy_end", loc, "MLOAD"])
        elif opcode == "istore":
            loc = inst.operands[1].value
            assembly.extend(["_OFST", "_mem_deploy_end", loc, "MSTORE"])
        else:
            raise Exception(f"Unknown opcode: {opcode}")

        # Step 6: Emit instructions output operands (if any)
        if inst.ret is not None:
            assert isinstance(inst.ret, IRVariable), "Return value must be a variable"
            if inst.ret.mem_type == MemType.MEMORY:
                assembly.extend([*PUSH(inst.ret.mem_addr)])

        return assembly

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

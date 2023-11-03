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
from vyper.venom.passes.dft import DFG
from vyper.venom.stack_model import StackModel


ONE_TO_ONE_INSTRUCTIONS = frozenset(
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


class VenomCompiler:
    label_counter = 0
    visited_instructions = None  # {IRInstruction}
    visited_basicblocks = None  # {IRBasicBlock}

    def generate_evm(self, ctx: IRFunction, no_optimize: bool = False) -> list[str]:
        self.visited_instructions = OrderedSet()
        self.visited_basicblocks = OrderedSet()
        self.label_counter = 0

        stack = StackModel()
        asm = []

        calculate_cfg(ctx)
        calculate_liveness(ctx)
        DFG.calculate_dfg(ctx)

        self._generate_evm_for_basicblock_r(ctx, asm, ctx.basic_blocks[0], stack)

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
        for inst in ctx.data_segment:
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
        self, assembly: list, stack: StackModel, stack_ops: OrderedSet[IRVariable]
    ) -> None:
        # make a list so we can index it
        stack_ops = [x for x in stack_ops]

        # print("ENTER reorder", stack.stack, operands)
        # start_len = len(assembly)
        for i in range(len(stack_ops)):
            op = stack_ops[i]
            final_stack_depth = -(len(stack_ops) - i - 1)
            depth = stack.get_depth(op)

            if depth == final_stack_depth:
                continue

            # print("trace", depth, final_stack_depth)
            stack.swap(assembly, depth)
            stack.swap(assembly, final_stack_depth)

        # print("INSTRUCTIONS", assembly[start_len:])
        # print("EXIT reorder", stack.stack, stack_ops)

    # REVIEW: possible swap implementation
    # def swap(self, op):
    #     depth = self.stack.get_depth(op)
    #     assert depth is not StackModel.NOT_IN_STACK, f"not in stack: {op}"
    #     self.stack.swap(depth)
    #     self.assembly.append(_evm_swap_for(depth))  # f"SWAP{-depth}")

    def _emit_input_operands(
        self,
        # REVIEW: ctx, assembly and stack could be moved onto the VenomCompiler instance
        ctx: IRFunction,
        assembly: list,
        inst: IRInstruction,
        ops: list[IRValueBase],
        stack: StackModel,
    ):
        # PRE: we already have all the items on the stack that have
        # been scheduled to be killed. now it's just a matter of emitting
        # SWAPs, DUPs and PUSHes until we match the `ops` argument

        # print("EMIT INPUTS FOR", inst)

        # dumb heuristic: if the top of stack is not wanted here, swap
        # it with something that is wanted
        if ops and stack.stack and stack.stack[-1] not in ops:
            for op in ops:
                if isinstance(op, IRVariable) and op not in inst.dup_requirements:
                    # REVIEW: maybe move swap_op and dup_op onto this class, so that
                    # StackModel doesn't need to know about the assembly list
                    stack.swap_op(assembly, op)
                    break

        emitted_ops = []
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
                stack.dup_op(assembly, op)

            if op in emitted_ops:
                stack.dup_op(assembly, op)

            # REVIEW: this seems like it can be reordered across volatile
            # boundaries (which includes memory fences). maybe just
            # remove it entirely at this point
            if isinstance(op, IRVariable) and op.mem_type == MemType.MEMORY:
                assembly.extend([*PUSH(op.mem_addr)])
                assembly.append("MLOAD")

            emitted_ops.append(op)

    # REVIEW: remove asm and stack from recursion, move to self.
    def _generate_evm_for_basicblock_r(
        self, ctx: IRFunction, asm: list, basicblock: IRBasicBlock, stack: StackModel
    ):
        if basicblock in self.visited_basicblocks:
            return
        self.visited_basicblocks.add(basicblock)

        asm.append(f"_sym_{basicblock.label}")
        asm.append("JUMPDEST")

        for inst in basicblock.instructions:
            asm = self._generate_evm_for_instruction(ctx, asm, inst, stack)

        for bb in basicblock.cfg_out:
            self._generate_evm_for_basicblock_r(ctx, asm, bb, stack.copy())

    # REVIEW: would this be better as a class?
    # HK: Let's consider it after the pass_dft refactor
    def _generate_evm_for_instruction(
        self, ctx: IRFunction, assembly: list, inst: IRInstruction, stack: StackModel
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
                stack.dup(assembly, depth)
                stack.poke(0, ret)
            else:
                stack.poke(depth, ret)
            return assembly

        # Step 2: Emit instruction's input operands
        self._emit_input_operands(ctx, assembly, inst, operands, stack)

        # Step 3: Reorder stack
        if opcode in ["jnz", "jmp"]:
            assert isinstance(inst.parent.cfg_out, OrderedSet)
            b = next(iter(inst.parent.cfg_out))
            target_stack = b.in_vars_from(inst.parent)
            self._stack_reorder(assembly, stack, target_stack)

        # print("pre-dups (inst)", inst.dup_requirements, stack.stack, inst)

        self._stack_reorder(assembly, stack, operands)
        # print("post-reorder (inst)", stack.stack, inst)

        # REVIEW: it would be clearer if the order of steps 4 and 5 were
        # switched (so that the runtime order matches the order they appear
        # below).
        # Step 4: Push instruction's return value to stack
        stack.pop(len(operands))
        if inst.ret is not None:
            stack.push(inst.ret)

        # Step 5: Emit the EVM instruction(s)
        if opcode in ONE_TO_ONE_INSTRUCTIONS:
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

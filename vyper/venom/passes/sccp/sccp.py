from dataclasses import dataclass
from enum import Enum
from functools import reduce
from typing import Union

from vyper.exceptions import CompilerPanic, StaticAssertionException
from vyper.utils import OrderedSet, int_bounds, int_log2, is_power_of_two
from vyper.venom.analysis import CFGAnalysis, DFGAnalysis, IRAnalysesCache, VarEquivalenceAnalysis
from vyper.venom.basicblock import (
    IRBasicBlock,
    IRInstruction,
    IRLabel,
    IRLiteral,
    IROperand,
    IRVariable,
)
from vyper.venom.function import IRFunction
from vyper.venom.passes.base_pass import IRPass
from vyper.venom.passes.sccp.eval import ARITHMETIC_OPS, signed_to_unsigned, unsigned_to_signed


class LatticeEnum(Enum):
    TOP = 1
    BOTTOM = 2


@dataclass
class SSAWorkListItem:
    inst: IRInstruction


@dataclass
class FlowWorkItem:
    start: IRBasicBlock
    end: IRBasicBlock


WorkListItem = Union[FlowWorkItem, SSAWorkListItem]
LatticeItem = Union[LatticeEnum, IRLiteral]
Lattice = dict[IRVariable, LatticeItem]


COMPARISON_OPS = {"gt", "sgt", "lt", "slt"}


def _flip_comparison_op(opname):
    assert opname in COMPARISON_OPS
    if "g" in opname:
        return opname.replace("g", "l")
    if "l" in opname:
        return opname.replace("l", "g")
    raise CompilerPanic(f"bad comparison op {opname}")  # pragma: nocover


def _wrap256(x, unsigned: bool):
    x %= 2**256
    # wrap in a signed way.
    if not unsigned:
        x = unsigned_to_signed(x, 256, strict=True)
    return x


class SCCP(IRPass):
    """
    This class implements the Sparse Conditional Constant Propagation
    algorithm by Wegman and Zadeck. It is a forward dataflow analysis
    that propagates constant values through the IR graph. It is used
    to optimize the IR by removing dead code and replacing variables
    with their constant values.
    """

    fn: IRFunction
    dfg: DFGAnalysis
    lattice: Lattice
    work_list: list[WorkListItem]
    cfg_in_exec: dict[IRBasicBlock, OrderedSet[IRBasicBlock]]
    sccp_calculated: set[IRBasicBlock]

    cfg_dirty: bool

    def __init__(self, analyses_cache: IRAnalysesCache, function: IRFunction):
        super().__init__(analyses_cache, function)
        self.lattice = {}
        self.work_list: list[WorkListItem] = []
        self.cfg_dirty = False

    def run_pass(self):
        self.fn = self.function
        self.analyses_cache.request_analysis(CFGAnalysis)
        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)  # type: ignore
        self.sccp_calculated = set()

        self.recalc_reachable = True
        self._calculate_sccp(self.fn.entry)
        self.last = False
        while True:
            # TODO compute uses and sccp only once
            # and then modify them on the fly
            self._propagate_constants()
            if not self._algebraic_opt():
                self.last = True
                break

        self._algebraic_opt()
        if self.cfg_dirty:
            self.analyses_cache.force_analysis(CFGAnalysis)
            self.fn.remove_unreachable_blocks()

    def _calculate_sccp(self, entry: IRBasicBlock):
        """
        This method is the main entry point for the SCCP algorithm. It
        initializes the work list and the lattice and then iterates over
        the work list until it is empty. It then visits each basic block
        in the CFG and processes the instructions in the block.

        This method does not update the IR, it only updates the lattice
        and the work list. The `_propagate_constants()` method is responsible
        for updating the IR with the constant values.
        """
        self.cfg_in_exec = {bb: OrderedSet() for bb in self.fn.get_basic_blocks()}

        dummy = IRBasicBlock(IRLabel("__dummy_start"), self.fn)
        self.work_list.append(FlowWorkItem(dummy, entry))

        # Initialize the lattice with TOP values for all variables
        for v in self.dfg._dfg_outputs:
            self.lattice[v] = LatticeEnum.TOP

        # Iterate over the work list until it is empty
        # Items in the work list can be either FlowWorkItem or SSAWorkListItem
        while len(self.work_list) > 0:
            work_item = self.work_list.pop()
            if isinstance(work_item, FlowWorkItem):
                self._handle_flow_work_item(work_item)
            elif isinstance(work_item, SSAWorkListItem):
                self._handle_SSA_work_item(work_item)
            else:
                raise CompilerPanic("Invalid work item type")

    def _handle_flow_work_item(self, work_item: FlowWorkItem):
        """
        This method handles a FlowWorkItem.
        """
        start = work_item.start
        end = work_item.end
        if start in self.cfg_in_exec[end]:
            return
        self.cfg_in_exec[end].add(start)

        self.sccp_calculated.add(end)

        for inst in end.instructions:
            if inst.opcode == "phi":
                self._visit_phi(inst)
            else:
                # Stop at the first non-phi instruction
                # as phis are only valid at the beginning of a block
                break

        if len(self.cfg_in_exec[end]) == 1:
            for inst in end.instructions:
                if inst.opcode == "phi":
                    continue
                self._visit_expr(inst)

        if len(end.cfg_out) == 1:
            self.work_list.append(FlowWorkItem(end, end.cfg_out.first()))

    def _handle_SSA_work_item(self, work_item: SSAWorkListItem):
        """
        This method handles a SSAWorkListItem.
        """
        if work_item.inst.opcode == "phi":
            self._visit_phi(work_item.inst)
        elif len(self.cfg_in_exec[work_item.inst.parent]) > 0:
            self._visit_expr(work_item.inst)

    def _lookup_from_lattice(self, op: IROperand) -> LatticeItem:
        assert isinstance(op, IRVariable), "Can't get lattice for non-variable"
        lat = self.lattice[op]
        assert lat is not None, f"Got undefined var {op}"
        return lat

    def _set_lattice(self, op: IROperand, value: LatticeItem):
        assert isinstance(op, IRVariable), "Can't set lattice for non-variable"
        self.lattice[op] = value

    def _eval_from_lattice(self, op: IROperand) -> IRLiteral | LatticeEnum:
        if isinstance(op, IRLiteral):
            return op

        return self._lookup_from_lattice(op)

    def _visit_phi(self, inst: IRInstruction):
        assert inst.opcode == "phi", "Can't visit non phi instruction"
        in_vars: list[LatticeItem] = []
        for bb_label, var in inst.phi_operands:
            bb = self.fn.get_basic_block(bb_label.name)
            if bb not in self.cfg_in_exec[inst.parent]:
                continue
            in_vars.append(self._lookup_from_lattice(var))
        value = reduce(_meet, in_vars, LatticeEnum.TOP)  # type: ignore

        if inst.output not in self.lattice:
            return

        if value != self._lookup_from_lattice(inst.output):
            self._set_lattice(inst.output, value)
            self._add_ssa_work_items(inst)

    def _visit_expr(self, inst: IRInstruction):
        opcode = inst.opcode
        if opcode in ["store", "alloca", "palloca"]:
            assert inst.output is not None, "Got store/alloca without output"
            out = self._eval_from_lattice(inst.operands[0])
            self._set_lattice(inst.output, out)
            self._add_ssa_work_items(inst)
        elif opcode == "jmp":
            target = self.fn.get_basic_block(inst.operands[0].value)
            self.work_list.append(FlowWorkItem(inst.parent, target))
        elif opcode == "jnz":
            lat = self._eval_from_lattice(inst.operands[0])

            assert lat != LatticeEnum.TOP, f"Got undefined var at jmp at {inst.parent}"
            if lat == LatticeEnum.BOTTOM:
                for out_bb in inst.parent.cfg_out:
                    self.work_list.append(FlowWorkItem(inst.parent, out_bb))
            else:
                self.cfg_dirty = True
                if _meet(lat, IRLiteral(0)) == LatticeEnum.BOTTOM:
                    target = self.fn.get_basic_block(inst.operands[1].name)
                    self.work_list.append(FlowWorkItem(inst.parent, target))
                if _meet(lat, IRLiteral(1)) == LatticeEnum.BOTTOM:
                    target = self.fn.get_basic_block(inst.operands[2].name)
                    self.work_list.append(FlowWorkItem(inst.parent, target))
        elif opcode == "djmp":
            lat = self._eval_from_lattice(inst.operands[0])
            assert lat != LatticeEnum.TOP, f"Got undefined var at jmp at {inst.parent}"
            if lat == LatticeEnum.BOTTOM:
                for op in inst.operands[1:]:
                    target = self.fn.get_basic_block(op.name)
                    self.work_list.append(FlowWorkItem(inst.parent, target))
            elif isinstance(lat, IRLiteral):
                raise CompilerPanic("Unimplemented djmp with literal")

        elif opcode in ["param", "calldataload"]:
            self.lattice[inst.output] = LatticeEnum.BOTTOM  # type: ignore
            self._add_ssa_work_items(inst)
        elif opcode == "mload":
            self.lattice[inst.output] = LatticeEnum.BOTTOM  # type: ignore
        elif opcode in ARITHMETIC_OPS:
            self._eval(inst)
        else:
            if inst.output is not None:
                self._set_lattice(inst.output, LatticeEnum.BOTTOM)

    def _eval(self, inst) -> LatticeItem:
        """
        This method evaluates an arithmetic operation and returns the result.
        At the same time it updates the lattice with the result and adds the
        instruction to the SSA work list if the knowledge about the variable
        changed.
        """

        def finalize(ret):
            # Update the lattice if the value changed
            old_val = self.lattice.get(inst.output, LatticeEnum.TOP)
            if old_val != ret:
                self.lattice[inst.output] = ret
                self._add_ssa_work_items(inst)
            return ret

        opcode = inst.opcode
        ops: list[IROperand] = []
        for op in inst.operands:
            # Evaluate the operand according to the lattice
            if isinstance(op, IRLabel):
                return finalize(LatticeEnum.BOTTOM)
            elif isinstance(op, IRVariable):
                eval_result = self.lattice[op]
            else:
                eval_result = op

            # If any operand is BOTTOM, the whole operation is BOTTOM
            # and we can stop the evaluation early
            if eval_result is LatticeEnum.BOTTOM:
                return finalize(LatticeEnum.BOTTOM)

            assert isinstance(eval_result, IROperand), f"yes {(inst.parent.label, op, inst)}"
            ops.append(eval_result)

        # If we haven't found BOTTOM yet, evaluate the operation
        fn = ARITHMETIC_OPS[opcode]
        return finalize(IRLiteral(fn(ops)))

    def _add_ssa_work_items(self, inst: IRInstruction):
        for target_inst in self.dfg.get_uses(inst.output):  # type: ignore
            self.work_list.append(SSAWorkListItem(target_inst))

    def _get_uses(self, var: IRVariable) -> OrderedSet:
        return self.dfg.get_uses(var)

    def _propagate_constants(self):
        """
        This method iterates over the IR and replaces constant values
        with their actual values. It also replaces conditional jumps
        with unconditional jumps if the condition is a constant value.
        """
        self.recalc_reachable = False
        for bb in self.function.get_basic_blocks():
            for inst in bb.instructions:
                self._replace_constants(inst)

    def _replace_constants(self, inst: IRInstruction):
        """
        This method replaces constant values in the instruction with
        their actual values. It also updates the instruction opcode in
        case of jumps and asserts as needed.
        """
        if inst.opcode == "jnz":
            lat = self._eval_from_lattice(inst.operands[0])

            if isinstance(lat, IRLiteral):
                if lat.value == 0:
                    target = inst.operands[2]
                else:
                    target = inst.operands[1]
                if isinstance(inst.operands[0], IRVariable):
                    self._get_uses(inst.operands[0]).remove(inst)
                inst.opcode = "jmp"
                inst.operands = [target]

                self.recalc_reachable = True
                self.cfg_dirty = True

        elif inst.opcode in ("assert", "assert_unreachable"):
            lat = self._eval_from_lattice(inst.operands[0])

            if isinstance(lat, IRLiteral):
                if lat.value > 0:
                    inst.opcode = "nop"
                    inst.operands = []
                elif len(inst.parent.cfg_in) == 1 or inst.parent == inst.parent.parent.entry:
                    raise StaticAssertionException(
                        f"assertion found to fail at compile time ({inst.error_msg}).",
                        inst.get_ast_source(),
                    )

        elif inst.opcode == "phi":
            return

        for i, op in enumerate(inst.operands):
            if isinstance(op, IRVariable):
                lat = self.lattice[op]
                if isinstance(lat, IRLiteral):
                    inst.operands[i] = lat

    def _fix_phi_nodes(self):
        # fix basic blocks whose cfg in was changed
        # maybe this should really be done in _visit_phi
        for bb in self.fn.get_basic_blocks():
            cfg_in_labels = OrderedSet(in_bb.label for in_bb in bb.cfg_in)

            needs_sort = False
            for inst in bb.instructions:
                if inst.opcode != "phi":
                    break
                needs_sort |= self._fix_phi_inst(inst, cfg_in_labels)

            # move phi instructions to the top of the block
            if needs_sort:
                bb.instructions.sort(key=lambda inst: inst.opcode != "phi")

    def _fix_phi_inst(self, inst: IRInstruction, cfg_in_labels: OrderedSet):
        operands = [op for label, op in inst.phi_operands if label in cfg_in_labels]

        if len(operands) != 1:
            return False

        assert inst.output is not None
        inst.opcode = "store"
        inst.operands = operands
        return True

    def _algebraic_opt(self) -> bool:
        self.eq = self.analyses_cache.force_analysis(VarEquivalenceAnalysis)
        assert isinstance(self.eq, VarEquivalenceAnalysis)

        change = False
        for bb in self.sccp_calculated:
            for inst in bb.instructions:
                change |= self._handle_inst_peephole(inst)

        return change

    def update(
        self, inst: IRInstruction, opcode: str, *args: IROperand | int, force: bool = False
    ) -> bool:
        assert opcode != "phi"
        if not force and inst.opcode == opcode:
            return False

        for op in inst.operands:
            if isinstance(op, IRVariable):
                uses = self._get_uses(op)
                if inst in uses:
                    uses.remove(inst)
        inst.opcode = opcode
        inst.operands = [arg if isinstance(arg, IROperand) else IRLiteral(arg) for arg in args]

        for op in inst.operands:
            if isinstance(op, IRVariable):
                self._get_uses(op).add(inst)

        self._visit_expr(inst)

        return True

    def store(self, inst: IRInstruction, *args: IROperand | int) -> bool:
        return self.update(inst, "store", *args)

    def add(self, inst: IRInstruction, opcode: str, *args: IROperand | int) -> IRVariable:
        assert opcode != "phi"
        index = inst.parent.instructions.index(inst)
        var = inst.parent.parent.get_next_variable()
        operands = [arg if isinstance(arg, IROperand) else IRLiteral(arg) for arg in args]
        new_inst = IRInstruction(opcode, operands, output=var)
        inst.parent.insert_instruction(new_inst, index)
        for op in new_inst.operands:
            if isinstance(op, IRVariable):
                self._get_uses(op).add(new_inst)
        self._get_uses(var).add(inst)
        self.dfg.set_producing_instruction(var, new_inst)
        self._visit_expr(new_inst)
        return var

    def is_lit(self, operand: IROperand) -> bool:
        if isinstance(operand, IRLabel):
            return False
        if isinstance(operand, IRVariable) and operand not in self.lattice:
            return False
        return isinstance(self._eval_from_lattice(operand), IRLiteral)

    def get_lit(self, operand: IROperand) -> IRLiteral:
        x = self._eval_from_lattice(operand)
        assert isinstance(x, IRLiteral), f"is not literal {x}"
        return x

    def lit_eq(self, operand: IROperand, val: int) -> bool:
        return self.is_lit(operand) and self.get_lit(operand).value == val

    def op_eq(self, operands, idx_a: int, idx_b: int) -> bool:
        if self.is_lit(operands[idx_a]) and self.is_lit(operands[idx_b]):
            return self.get_lit(operands[idx_a]) == self.get_lit(operands[idx_b])
        else:
            assert isinstance(self.eq, VarEquivalenceAnalysis)
            return self.eq.equivalent(operands[idx_a], operands[idx_b])

    def _handle_inst_peephole(self, inst: IRInstruction) -> bool:
        if inst.opcode != "assert" and inst.is_volatile:
            return False
        if inst.opcode == "store":
            return False
        if inst.is_pseudo:
            return False
        if inst.is_bb_terminator:
            return False

        operands = inst.operands

        if (
            inst.opcode == "add"
            and self.is_lit(operands[0])
            and isinstance(self.get_lit(operands[0]), IRLiteral)
            and isinstance(inst.operands[1], IRLabel)
        ):
            inst.opcode = "offset"
            return True

        if inst.is_commutative and self.is_lit(operands[1]):
            operands = [operands[1], operands[0]]

        if inst.opcode == "iszero" and self.is_lit(operands[0]):
            lit = self.get_lit(operands[0]).value
            val = int(lit == 0)
            return self.store(inst, val)

        if inst.opcode in {"shl", "shr", "sar"} and self.lit_eq(operands[1], 0):
            return self.store(inst, operands[0])

        if inst.opcode in {"add", "sub", "xor", "or"} and self.lit_eq(operands[0], 0):
            return self.store(inst, operands[1])

        if inst.opcode in {"mul", "div", "sdiv", "mod", "smod", "and"} and self.lit_eq(
            operands[0], 0
        ):
            return self.store(inst, 0)

        if inst.opcode in {"mul", "div", "sdiv"} and self.lit_eq(operands[0], 1):
            return self.store(inst, operands[1])

        if inst.opcode == "sub" and self.lit_eq(operands[1], -1):
            return self.update(inst, "not", operands[0])

        if inst.opcode == "exp" and self.lit_eq(operands[0], 0):
            return self.store(inst, 1)

        if inst.opcode == "exp" and self.lit_eq(operands[1], 1):
            return self.store(inst, 1)

        if inst.opcode == "exp" and self.lit_eq(operands[1], 0):
            return self.update(inst, "iszero", operands[0])

        if inst.opcode == "exp" and self.lit_eq(operands[0], 1):
            return self.store(inst, operands[1])

        if inst.opcode == "eq" and self.lit_eq(operands[0], 0):
            return self.update(inst, "iszero", operands[1])

        if inst.opcode == "eq" and self.lit_eq(operands[1], 0):
            return self.update(inst, "iszero", operands[0])

        if inst.opcode in {"sub", "xor", "ne"} and self.op_eq(operands, 0, 1):
            # (x - x) == (x ^ x) == (x != x) == 0
            return self.store(inst, 0)

        if inst.opcode in COMPARISON_OPS and self.op_eq(operands, 0, 1):
            # (x < x) == (x > x) == 0
            return self.store(inst, 0)

        if inst.opcode in {"eq"} and self.op_eq(operands, 0, 1):
            # (x == x) == 1
            return self.store(inst, 1)

        if inst.opcode in {"mod", "smod"} and self.lit_eq(operands[0], 1):
            return self.store(inst, 0)

        if inst.opcode == "and" and self.lit_eq(operands[0], signed_to_unsigned(-1, 256)):
            return self.store(inst, operands[1])

        if inst.opcode == "xor" and self.lit_eq(operands[0], signed_to_unsigned(-1, 256)):
            return self.update(inst, "not", operands[1])

        if inst.opcode == "or" and self.lit_eq(operands[0], signed_to_unsigned(-1, 256)):
            return self.store(inst, signed_to_unsigned(-1, 256))

        if (
            inst.opcode in {"mod", "div", "mul"}
            and self.is_lit(operands[0])
            and is_power_of_two(self.get_lit(operands[0]).value)
        ):
            val = self.get_lit(operands[0]).value
            if inst.opcode == "mod":
                return self.update(inst, "and", val - 1, operands[1])
            if inst.opcode == "div":
                return self.update(inst, "shr", operands[1], int_log2(val))
            if inst.opcode == "mul":
                return self.update(inst, "shl", operands[1], int_log2(val))

        if inst.opcode == "assert" and isinstance(operands[0], IRVariable):
            src = self.dfg.get_producing_instruction(operands[0])
            assert isinstance(src, IRInstruction)
            if src.opcode not in COMPARISON_OPS:
                return False

            assert isinstance(src.output, IRVariable)
            uses = self.dfg.get_uses(src.output)
            if len(uses) != 1:
                return False

            if not isinstance(src.operands[0], IRLiteral):
                return False

            n_op = src.operands[0].value
            if "gt" in src.opcode:
                n_op += 1
            else:
                n_op -= 1
            unsigned = "s" not in src.opcode

            assert _wrap256(n_op, unsigned) == n_op, "bad optimizer step"
            n_opcode = (
                src.opcode.replace("g", "l") if "g" in src.opcode else src.opcode.replace("l", "g")
            )

            src.opcode = n_opcode
            src.operands = [IRLiteral(n_op), src.operands[1]]

            var = self.add(inst, "iszero", src.output)
            self.dfg.add_use(var, inst)

            self.update(inst, "assert", var, force=True)

            return True

        if inst.output is None:
            return False

        assert isinstance(inst.output, IRVariable), "must be variable"
        uses = self.dfg.get_uses_ignore_nops(inst.output)
        is_truthy = all(i.opcode in ("assert", "iszero", "jnz") for i in uses)

        if is_truthy:
            if inst.opcode == "eq":
                # (eq x y) has the same truthyness as (iszero (xor x y))
                # it also has the same truthyness as (iszero (sub x y)),
                # but xor is slightly easier to optimize because of being
                # commutative.
                # note that (xor (-1) x) has its own rule
                tmp = self.add(inst, "xor", operands[0], operands[1])

                return self.update(inst, "iszero", tmp)
            if (
                inst.opcode == "or"
                and self.is_lit(operands[0])
                and self.get_lit(operands[0]).value != 0
            ):
                return self.store(inst, 1)

        if inst.opcode in COMPARISON_OPS:
            prefer_strict = not is_truthy
            opcode = inst.opcode
            if self.is_lit(operands[1]):
                opcode = _flip_comparison_op(inst.opcode)
                operands = [operands[1], operands[0]]

            is_gt = "g" in opcode

            unsigned = "s" not in opcode

            lo, hi = int_bounds(bits=256, signed=not unsigned)

            # for comparison operators, we have three special boundary cases:
            # almost always, never and almost never.
            # almost_always is always true for the non-strict ("ge" and co)
            # comparators. for strict comparators ("gt" and co), almost_always
            # is true except for one case. never is never true for the strict
            # comparators. never is almost always false for the non-strict
            # comparators, except for one case. and almost_never is almost
            # never true (except one case) for the strict comparators.
            if is_gt:
                almost_always, never = lo, hi
                almost_never = hi - 1
            else:
                almost_always, never = hi, lo
                almost_never = lo + 1

            if self.is_lit(operands[0]) and self.get_lit(operands[0]).value == never:
                # e.g. gt x MAX_UINT256, slt x MIN_INT256
                return self.store(inst, 0)

            if self.is_lit(operands[0]) and self.get_lit(operands[0]).value == almost_never:
                # (lt x 1), (gt x (MAX_UINT256 - 1)), (slt x (MIN_INT256 + 1))
                return self.update(inst, "eq", operands[1], never)

            # rewrites. in positions where iszero is preferred, (gt x 5) => (ge x 6)
            if (
                not prefer_strict
                and self.is_lit(operands[0])
                and self.get_lit(operands[0]).value == almost_always
            ):
                # e.g. gt x 0, slt x MAX_INT256
                tmp = self.add(inst, "eq", *operands)
                return self.update(inst, "iszero", tmp)

            # special cases that are not covered by others:

            if opcode == "gt" and self.is_lit(operands[0]) and self.get_lit(operands[0]) == 0:
                # improve codesize (not gas), and maybe trigger
                # downstream optimizations
                tmp = self.add(inst, "iszero", operands[1])
                return self.update(inst, "iszero", tmp)

            # only done in last iteration because on average if not already optimize
            # this rule creates bigger codesize because it could interfere with other
            # optimizations
            if (
                self.last
                and len(uses) == 1
                and uses.first().opcode == "iszero"
                and self.is_lit(operands[0])
            ):
                after = uses.first()
                n_uses = self.dfg.get_uses(after.output)
                if len(n_uses) != 1 or n_uses.first().opcode in ["iszero", "assert"]:
                    return False

                n_op = self.get_lit(operands[0]).value
                if "gt" in opcode:
                    n_op += 1
                else:
                    n_op -= 1

                assert _wrap256(n_op, unsigned) == n_op, "bad optimizer step"
                n_opcode = opcode.replace("g", "l") if "g" in opcode else opcode.replace("l", "g")
                self.update(inst, n_opcode, n_op, operands[1], force=True)
                uses.first().opcode = "store"
                self._visit_expr(uses.first())
                return True

        return False


def _meet(x: LatticeItem, y: LatticeItem) -> LatticeItem:
    if x == LatticeEnum.TOP:
        return y
    if y == LatticeEnum.TOP or x == y:
        return x
    return LatticeEnum.BOTTOM

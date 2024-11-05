from dataclasses import dataclass
from enum import Enum
from functools import reduce
from typing import Union

from vyper.exceptions import CompilerPanic, StaticAssertionException
from vyper.utils import OrderedSet, int_bounds, int_log2, is_power_of_two
from vyper.venom.analysis import (
    CFGAnalysis,
    DFGAnalysis,
    DominatorTreeAnalysis,
    IRAnalysesCache,
    VarEquivalenceAnalysis,
)
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
    dom: DominatorTreeAnalysis
    dfg: DFGAnalysis
    lattice: Lattice
    work_list: list[WorkListItem]
    cfg_in_exec: dict[IRBasicBlock, OrderedSet[IRBasicBlock]]

    cfg_dirty: bool

    def __init__(self, analyses_cache: IRAnalysesCache, function: IRFunction):
        super().__init__(analyses_cache, function)
        self.lattice = {}
        self.work_list: list[WorkListItem] = []
        self.cfg_dirty = False

    def run_pass(self):
        self.fn = self.function
        self.dom = self.analyses_cache.request_analysis(DominatorTreeAnalysis)  # type: ignore
        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)  # type: ignore

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
            self._fix_phi_nodes()


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
        opcode = inst.opcode

        ops = []
        for op in inst.operands:
            if isinstance(op, IRVariable):
                ops.append(self.lattice[op])
            elif isinstance(op, IRLabel):
                return LatticeEnum.BOTTOM
            else:
                ops.append(op)

        ret = None
        if LatticeEnum.BOTTOM in ops:
            ret = LatticeEnum.BOTTOM
        else:
            if opcode in ARITHMETIC_OPS:
                fn = ARITHMETIC_OPS[opcode]
                ret = IRLiteral(fn(ops))  # type: ignore
            elif len(ops) > 0:
                ret = ops[0]  # type: ignore
            else:
                raise CompilerPanic("Bad constant evaluation")

        old_val = self.lattice.get(inst.output, LatticeEnum.TOP)
        if old_val != ret:
            self.lattice[inst.output] = ret  # type: ignore
            self._add_ssa_work_items(inst)

        return ret  # type: ignore

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
        # the reachability is needed because of the
        # unreachable assert that would be statically
        # found to be false, but we still assume that
        # the unreachable basic block will be handled
        # with all other aspects in sccp test
        if self.recalc_reachable:
            self.function._compute_reachability()
        self.recalc_reachable = False
        for bb in self.dom.dfs_walk:
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
                elif inst.parent.is_reachable:
                    raise StaticAssertionException(
                        f"assertion found to fail at compile time ({inst.error_msg}).",
                        inst.get_ast_source(),
                    )

                inst.operands = []

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
        full_change = False
        while True:
            change = False
            for bb in self.function.get_basic_blocks():
                for inst in bb.instructions:
                    change |= self._handle_inst_peephole(inst)
            full_change |= change

            if not change:
                break
        return full_change

    def _handle_inst_peephole(self, inst: IRInstruction) -> bool:
        def update(opcode: str, *args: IROperand | int, force: bool = False) -> bool:
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

        def store(*args: IROperand | int) -> bool:
            return update("store", *args)

        def add(opcode: str, *args: IROperand | int) -> IRVariable:
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
            self._visit_expr(new_inst)
            return var

        operands = inst.operands

        def match(opcodes: set[str], *ops: int | None):
            if inst.opcode not in opcodes:
                return False

            assert len(ops) == len(operands), "wrong number of operands"
            for cond_op, op in zip(ops, operands):
                if cond_op is None:
                    continue
                if not isinstance(op, IRLiteral):
                    return False
                if op.value != cond_op:
                    return False
            return True

        def is_lit(index: int) -> bool:
            if isinstance(operands[index], IRLabel):
                return False
            if isinstance(operands[index], IRVariable) and operands[index] not in self.lattice:
                return False
            return isinstance(self._eval_from_lattice(operands[index]), IRLiteral)

        def get_lit(index: int) -> IRLiteral:
            x = self._eval_from_lattice(operands[index])
            assert isinstance(x, IRLiteral), f"is not literal {x}"
            return x

        def op_eq(idx_a: int, idx_b: int) -> bool:
            if is_lit(idx_a) and is_lit(idx_b):
                return get_lit(idx_a) == get_lit(idx_b)
            else:
                assert isinstance(self.eq, VarEquivalenceAnalysis)
                return self.eq.equivalent(operands[idx_a], operands[idx_b])

        if (
            inst.opcode == "add"
            and is_lit(0)
            and isinstance(get_lit(0), IRLiteral)
            and isinstance(inst.operands[1], IRLabel)
        ):
            inst.opcode = "offset"
            return True

        if inst.is_commutative and is_lit(1):
            operands = [operands[1], operands[0]]

        if inst.opcode in ARITHMETIC_OPS and all(is_lit(i) for i in range(len(operands))):
            oper = ARITHMETIC_OPS[inst.opcode]
            val = oper([get_lit(i) for i in range(len(operands))])
            return store(val)

        if inst.opcode == "iszero" and is_lit(0):
            lit = get_lit(0).value
            val = int(lit == 0)
            return store(val)

        if match({"shl", "shr", "sar"}, None, 0):
            return store(operands[0])

        if match({"add", "sub", "xor", "or"}, 0, None):
            return store(operands[1])

        if match({"mul", "div", "sdiv", "mod", "smod", "and"}, 0, None):
            return store(0)

        if match({"mul", "div", "sdiv"}, 1, None):
            return store(operands[1])

        if match({"sub"}, None, -1):
            return update("not", operands[0])

        if match({"exp"}, 0, None):
            return store(1)

        if match({"exp"}, None, 1):
            return store(1)

        if match({"exp"}, None, 0):
            return update("iszero", operands[0])

        if match({"exp"}, 1, None):
            return store(operands[1])

        if match({"eq"}, 0, None):
            return update("iszero", operands[1])

        if match({"eq"}, None, 0):
            return update("iszero", operands[0])

        if inst.opcode in {"sub", "xor", "ne"} and op_eq(0, 1):
            # (x - x) == (x ^ x) == (x != x) == 0
            return store(0)

        if inst.opcode in COMPARISON_OPS and op_eq(0, 1):
            # (x < x) == (x > x) == 0
            return store(0)

        if inst.opcode in {"eq"} and op_eq(0, 1):
            # (x == x) == 1
            return store(1)

        if match({"mod", "smod"}, 1, None):
            return store(0)

        if match({"and"}, signed_to_unsigned(-1, 256), None):
            return store(operands[1])

        if match({"xor"}, signed_to_unsigned(-1, 256), None):
            return update("not", operands[1])

        if match({"or"}, signed_to_unsigned(-1, 256), None):
            return store(signed_to_unsigned(-1, 256))

        if inst.opcode in {"mod", "div", "mul"} and is_lit(0) and is_power_of_two(get_lit(0).value):
            val = get_lit(0).value
            if inst.opcode == "mod":
                return update("and", val - 1, operands[1])
            if inst.opcode == "div":
                return update("shr", operands[1], int_log2(val))
            if inst.opcode == "mul":
                return update("shl", operands[1], int_log2(val))

        if inst.output is None:
            return False

        assert isinstance(inst.output, IRVariable), "must be variable"
        uses = self.dfg.get_uses_ignore_stores(inst.output)
        is_truthy = all(i.opcode in ("assert", "iszero", "jnz") for i in uses)

        if is_truthy:
            if inst.opcode == "eq":
                # (eq x y) has the same truthyness as (iszero (xor x y))
                # it also has the same truthyness as (iszero (sub x y)),
                # but xor is slightly easier to optimize because of being
                # commutative.
                # note that (xor (-1) x) has its own rule
                tmp = add("xor", operands[0], operands[1])

                return update("iszero", tmp)
            if inst.opcode == "or" and is_lit(0) and get_lit(0).value != 0:
                return store(1)

        if inst.opcode in COMPARISON_OPS:
            prefer_strict = not is_truthy
            opcode = inst.opcode
            if is_lit(1):  # _is_int(args[0]):
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

            if is_lit(0) and get_lit(0).value == never:
                # e.g. gt x MAX_UINT256, slt x MIN_INT256
                return store(0)

            if is_lit(0) and get_lit(0).value == almost_never:
                # (lt x 1), (gt x (MAX_UINT256 - 1)), (slt x (MIN_INT256 + 1))
                return update("eq", operands[1], never)

            # rewrites. in positions where iszero is preferred, (gt x 5) => (ge x 6)
            if not prefer_strict and is_lit(0) and get_lit(0).value == almost_always:
                # e.g. gt x 0, slt x MAX_INT256
                tmp = add("eq", *operands)
                return update("iszero", tmp)

            # special cases that are not covered by others:

            if opcode == "gt" and is_lit(0) and get_lit(0) == 0:
                # improve codesize (not gas), and maybe trigger
                # downstream optimizations
                tmp = add("iszero", operands[1])
                return update("iszero", tmp)

            if self.last and len(uses) == 1 and uses.first().opcode == "iszero" and is_lit(0):
                after = uses.first()
                n_uses = self.dfg.get_uses(after.output)
                if len(n_uses) != 1 or n_uses.first().opcode in ["iszero", "assert"]:
                    return False

                n_op = get_lit(0).value
                if "gt" in opcode:
                    n_op += 1
                else:
                    n_op -= 1

                assert _wrap256(n_op, unsigned) == n_op, "bad optimizer step"
                n_opcode = opcode.replace("g", "l") if "g" in opcode else opcode.replace("l", "g")
                assert update(n_opcode, n_op, operands[1], force=True), "you stupid"
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

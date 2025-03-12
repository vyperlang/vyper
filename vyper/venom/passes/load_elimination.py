from collections import deque, defaultdict
from typing import Optional
from vyper.utils import OrderedSet

from vyper.venom.analysis import DFGAnalysis, LivenessAnalysis, CFGAnalysis
from vyper.venom.basicblock import IRLiteral, IRBasicBlock, IRInstruction
from vyper.venom.effects import Effects
from vyper.venom.passes.base_pass import InstUpdater, IRPass


def _conflict(store_opcode: str, k1: IRLiteral, k2: IRLiteral):
    ptr1, ptr2 = k1.value, k2.value
    # hardcode the size of store opcodes for now. maybe refactor to use
    # vyper.evm.address_space
    if store_opcode == "mstore":
        return abs(ptr1 - ptr2) < 32
    assert store_opcode in ("sstore", "tstore"), "unhandled store opcode"
    return abs(ptr1 - ptr2) < 1


class LoadElimination(IRPass):
    """
    Eliminate sloads, mloads and tloads
    """

    # should this be renamed to EffectsElimination?

    updater: InstUpdater

    def run_pass(self):
        cfg = self.analyses_cache.request_analysis(CFGAnalysis)
        # TODO: request_analysis
        self.dfg = self.analyses_cache.force_analysis(DFGAnalysis)
        self.updater = InstUpdater(self.dfg)

        self._big_lattice = defaultdict(lambda: defaultdict(dict))

        # seed with dfs pre walk
        worklist = OrderedSet(cfg.dfs_pre_walk)

        while len(worklist) > 0:
            changed = False

            bb = worklist.pop()

            changed |= self._process_bb(bb, Effects.MEMORY, "mload", "mstore")
            changed |= self._process_bb(bb, Effects.TRANSIENT, "tload", "tstore")
            changed |= self._process_bb(bb, Effects.STORAGE, "sload", "sstore")
            changed |= self._process_bb(bb, None, "dload", None)
            changed |= self._process_bb(bb, None, "calldataload", None)

            if changed:
                worklist.update(bb.cfg_out)

        for bb in self.function.get_basic_blocks():
            bb.ensure_well_formed()

        self.analyses_cache.invalidate_analysis(LivenessAnalysis)
        self.analyses_cache.invalidate_analysis(DFGAnalysis)

    def equivalent(self, op1, op2):
        return self.dfg.are_equivalent(op1, op2)
        return op1 == op2

    def get_literal(self, op):
        op = self.dfg._traverse_store_chain(op)
        if isinstance(op, IRLiteral):
            return op
        return None

    def _process_bb(self, bb, eff, load_opcode, store_opcode):
        # not really a lattice even though it is not really inter-basic block;
        # we may generalize in the future
        self.dfg = self.analyses_cache.force_analysis(DFGAnalysis)
        self._lattice = {}
        old_lattice = self._big_lattice[load_opcode][bb].copy()

        cfg_in = list(bb.cfg_in)
        if len(cfg_in) > 0:
            common_keys = self._big_lattice[load_opcode][cfg_in[0]].keys()
            for in_bb in cfg_in:
                common_keys &= self._big_lattice[load_opcode][in_bb].keys()

            for k in common_keys:
                # insert phi nodes and seed our lattice
                if k in self._lattice:
                    # already inserted the phi node, skip
                    continue

                phi_args = []
                for in_bb in bb.cfg_in:
                    in_values = self._big_lattice[load_opcode][in_bb]
                    phi_args.append(in_bb.label)

                    val = in_values[k]
                    phi_args.append(val)

                phi_out = self.function.get_next_variable()
                phi_inst = IRInstruction("phi", phi_args, output=phi_out)
                # TODO: update instupdater to handle phi
                bb.insert_instruction(phi_inst, index=0)
                #print("INSERT PHI", phi_inst)

                # fix degenerate phis
                if len(phi_args) == 2:
                    phi_inst.opcode = "store"
                    phi_inst.operands = [phi_args[1]]

                self._lattice[k] = phi_out

        #print("(pre)", old_lattice)
        #print(f"\n\nENTER {load_opcode} starting lattice", self._lattice)
        #print(bb)
        self.dfg = self.analyses_cache.force_analysis(DFGAnalysis)

        for inst in bb.instructions:
            if inst.opcode == store_opcode:
                self._handle_store(inst, store_opcode)

            elif eff is not None and eff in inst.get_write_effects():
                self._lattice = {}

            elif inst.opcode == load_opcode:
                self._handle_load(inst)

        for k, v in self._lattice.items():
            if v != old_lattice.get(k) and isinstance(v, IRLiteral):
                # produce variables mapping them to literals
                var = self.function.get_next_variable()
                bb.insert_instruction(IRInstruction("store", [v], var), index=-1)
                self._lattice[k] = var

        changed = (old_lattice != self._lattice)
        self._big_lattice[load_opcode][bb] = self._lattice
        #print(bb)
        #print(f"ENTER {load_opcode} ending lattice", self._lattice)
        #print("CHANGED", changed)

        self.dfg = self.analyses_cache.force_analysis(DFGAnalysis)

        return changed

    def _handle_load(self, inst):
        (ptr,) = inst.operands

        existing_value = self._lattice.get(ptr)

        assert inst.output is not None  # help mypy

        # "cache" the value for future load instructions
        self._lattice[ptr] = inst.output

        if existing_value is not None:
            inst.opcode = "store"
            inst.operands = [existing_value]

    def _handle_store(self, inst, store_opcode):
        # mstore [val, ptr]
        val, ptr = inst.operands

        known_ptr: Optional[IRLiteral] = self.get_literal(ptr)
        if known_ptr is None:
            # it's a variable. assign this ptr in the lattice and flush
            # everything else.
            self._lattice = {ptr: val}
            return

        # we found a redundant store, eliminate it
        existing_val = self._lattice.get(known_ptr)
        #print("EQUIVALENT", val, existing_val, self.equivalent(val, existing_val))
        if self.equivalent(val, existing_val):
            self.updater.nop(inst)
            return

        self._lattice[known_ptr] = val

        # kick out any conflicts
        for existing_key in self._lattice.copy().keys():
            if not isinstance(existing_key, IRLiteral):
                # a variable in the lattice. assign this ptr in the lattice
                # and flush everything else.
                self._lattice = {known_ptr: val}
                break

            if _conflict(store_opcode, known_ptr, existing_key):
                del self._lattice[existing_key]
                self._lattice[known_ptr] = val

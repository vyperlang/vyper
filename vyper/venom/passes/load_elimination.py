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
        self.cfg = self.analyses_cache.request_analysis(CFGAnalysis)
        # TODO: request_analysis
        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)
        self.updater = InstUpdater(self.dfg)

        self._run(Effects.MEMORY, "mload", "mstore")
        self._run(Effects.TRANSIENT, "tload", "tstore")
        self._run(Effects.STORAGE, "sload", "sstore")
        self._run(None, "dload", None)
        self._run(None, "calldataload", None)

        for bb in self.function.get_basic_blocks():
            bb.ensure_well_formed()

        self.analyses_cache.invalidate_analysis(LivenessAnalysis)
        self.analyses_cache.invalidate_analysis(DFGAnalysis)

        #print(self.function)

    def _run(self, eff, load_opcode, store_opcode):
        self._big_lattice = defaultdict(dict)

        # seed with dfs pre walk
        worklist = OrderedSet(self.cfg.dfs_post_walk)

        while len(worklist) > 0:
            bb = worklist.pop()

            changed = self._process_bb(bb, eff, load_opcode, store_opcode)
            if changed:
                worklist.update(bb.cfg_out)

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
        old_lattice = self._big_lattice[bb].copy()

        cfg_in = list(bb.cfg_in)
        if len(cfg_in) > 0:
            common_keys = self._big_lattice[cfg_in[0]].keys()
            for in_bb in cfg_in:
                common_keys &= self._big_lattice[in_bb].keys()

            for k in common_keys:
                # insert phi nodes and seed our lattice
                if k in old_lattice:
                    # already inserted the phi node, skip
                    continue

                phi_args = []
                for in_bb in bb.cfg_in:
                    phi_args.append(in_bb.label)

                    in_values = self._big_lattice[in_bb]
                    val = in_values[k]
                    phi_args.append(val)

                if len(phi_args) == 2:
                    # fix degenerate phis
                    phi_out = self.updater.add_before(bb.instructions[0], "store", [phi_args[1]])
                else:
                    phi_out = self.updater.add_before(bb.instructions[0], "phi", phi_args)
                #print("INSERT PHI", phi_inst)
                self._lattice[k] = phi_out

        #print("(pre)", old_lattice)
        #print(f"\n\nENTER {load_opcode} starting lattice", self._lattice)
        #print(bb)
        #self.dfg = self.analyses_cache.force_analysis(DFGAnalysis)

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
                var = self.updater.add_before(bb.instructions[-1], "store", [v])
                self._lattice[k] = var

        changed = (old_lattice != self._lattice)
        self._big_lattice[bb] = self._lattice
        #print(bb)
        #print(f"ENTER {load_opcode} ending lattice", self._lattice)
        #print("CHANGED", changed)

        #self.dfg = self.analyses_cache.force_analysis(DFGAnalysis)

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

from vyper.venom.analysis import DFGAnalysis, LivenessAnalysis, DominatorTreeAnalysis
from vyper.venom.basicblock import IRInstruction, IRVariable, IRBasicBlock
from vyper.venom.passes.base_pass import InstUpdater, IRPass


class Graph:
    nodes: dict[IRVariable, IRInstruction]

    def __init__(self, insts: set[IRInstruction]):
        self.nodes = dict()
        for inst in insts:
            assert inst.output is not None
            self.nodes[inst.output] = inst
    
    def is_leaf(self, inst: IRInstruction) -> bool:
        if inst.opcode not in ("phi", "store"):
            return True
        return all(op not in self.nodes for op in inst.operands)
    
    def get_all_leafs(self) -> list[IRInstruction]:
        res = []
        for inst in self.nodes.values():
            if self.is_leaf(inst):
                res.append(inst)
        return res

    def get_leafs_by_phi(self, dfg: DFGAnalysis) -> dict[IRInstruction, set[IRInstruction]]:
        res: dict[IRInstruction, set[IRInstruction]] = dict()
        leafs = self.get_all_leafs()
        for inst in leafs:
            assert inst.output is not None
            uses = [use for use in dfg.get_uses(inst.output) if use.output in self.nodes]
            if len(uses) != 1:
                continue
            use = uses[0]
            assert isinstance(use, IRInstruction) # help mypy
            if use.opcode != "phi":
                continue
            assert use.output is not None
            if use.output not in self.nodes:
                continue
            if use not in res:
                res[use] = set()
            res[use].add(inst)

        for phi, phi_leafs in list(res.items()):
            if len(list(phi.phi_operands)) != len(phi_leafs):
                del res[phi]
        return res


    def get_non_phi_leafs(self, dfg: DFGAnalysis) -> list[IRInstruction]:
        res: list[IRInstruction] = []
        leafs = self.get_all_leafs()
        for inst in leafs:
            assert inst.output is not None
            uses = dfg.get_uses(inst.output)
            if any(u.opcode == "phi" for u in uses):
                continue
            res.append(inst)
        return res

    def remove_leafs(self, leafs: list[IRInstruction]):
        for inst in leafs:
            assert inst.output is not None
            del self.nodes[inst.output]

    def find_single_source(self, dfg: DFGAnalysis) -> IRInstruction | None:
        while len(self.nodes) > 0:
            leafs = self.get_all_leafs()
            if len(leafs) == 0:
                return None
            if len(leafs) == 1:
                return leafs[0]
            by_phi_leaf = self.get_leafs_by_phi(dfg)
            if len(by_phi_leaf) == 0:
                return None
                leafs = self.get_non_phi_leafs(dfg)
                if len(leafs) == 0:
                    return None
                self.remove_leafs(leafs)
                continue
            phi, phi_leafs = by_phi_leaf.popitem()
            assert phi.opcode == "phi"
            self.remove_leafs(list(phi_leafs))
        return None
        

class PhiEliminationPass(IRPass):
    phi_to_origins: dict[IRInstruction, set[IRInstruction]]
    phi_to_single_source: dict[IRInstruction, IRInstruction]

    def run_pass(self):
        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)
        self.updater = InstUpdater(self.dfg)
        self._calculate_phi_origin()

        for _, inst in self.dfg.outputs.copy().items():
            if inst.opcode != "phi":
                continue
            self._process_phi(inst)

        for bb in self.function.get_basic_blocks():
            bb.ensure_well_formed()

        self.analyses_cache.invalidate_analysis(LivenessAnalysis)

    def _process_phi(self, inst: IRInstruction):
        src = self.phi_to_single_source.get(inst)

        if src is not None:
            assert src.output is not None
            self.updater.store(inst, src.output)

    def _calculate_phi_origin(self):
        self.dfg = self.analyses_cache.request_analysis(DFGAnalysis)
        self.dom = self.analyses_cache.request_analysis(DominatorTreeAnalysis)
        self.phi_to_origins = dict()

        for bb in self.function.get_basic_blocks():
            bb.ensure_well_formed()
            for inst in bb.instructions:
                if inst.opcode != "phi":
                    break
                self._handle_phi(inst)

        self.phi_to_single_source = dict()
        for phi, sources in self.phi_to_origins.items():
            graph = Graph(sources)
            #print("PHI", phi)
            single = graph.find_single_source(self.dfg)
            #print("RES", single)
            if single is not None:
                self.phi_to_single_source[phi] = single

        for src_insts in self.phi_to_origins.values():
            # sanity check (it could be triggered if we get invalid venom)
            #assert all(src.opcode != "phi" for src in src_insts)
            pass

    def _handle_phi(self, inst: IRInstruction):
        assert inst.opcode == "phi"
        self._handle_inst_r(inst, inst.parent)

    def _handle_inst_r(self, inst: IRInstruction, origin_bb: IRBasicBlock) -> set[IRInstruction]:
        if inst.opcode == "phi":
            if inst in self.phi_to_origins:
                # phi is the only place where we can get dfg cycles.
                # break the recursion.
                return self.phi_to_origins[inst] | set([inst])

            self.phi_to_origins[inst] = set()

            for _, var in inst.phi_operands:
                next_inst = self.dfg.get_producing_instruction(var)
                assert next_inst is not None, (inst, var)
                self.phi_to_origins[inst] |= self._handle_inst_r(next_inst, origin_bb)
            return self.phi_to_origins[inst] | set([inst])

        if inst.opcode == "store" and isinstance(inst.operands[0], IRVariable):
            # traverse store chain
            var = inst.operands[0]
            next_inst = self.dfg.get_producing_instruction(var)
            assert next_inst is not None
            return self._handle_inst_r(next_inst, origin_bb) | set([inst])

        return set([inst])

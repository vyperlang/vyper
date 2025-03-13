from vyper.venom.analysis import CFGAnalysis
from vyper.venom.basicblock import IRInstruction, IRLiteral, IRVariable
from vyper.venom.passes.base_pass import IRPass


class SimplifyPhiPass(IRPass):
    """
    This pass eliminates phi nodes with identical operands.
    
    In SSA form, when all branches of a control flow join, phi nodes are created
    to select the appropriate value based on which branch was taken.
    
    However, when all operands of a phi node are the same, the phi node is redundant
    and can be replaced with a simple assignment.
    """
    
    def run_pass(self):
        """
        Runs the SimplifyPhi pass on the function.
        """
        # Request CFG analysis
        self.analyses_cache.request_analysis(CFGAnalysis)
        
        # Process all basic blocks in the function
        changed = False
        for bb in self.function.get_basic_blocks():
            # Look for phi nodes in the basic block
            for inst in list(bb.instructions):  # Use a copy since we might modify the list
                if inst.opcode == "phi":
                    # Check if the phi has identical operands
                    if self._has_identical_phi_operands(inst):
                        # Replace the phi with a simple assignment
                        self._replace_phi_with_assignment(inst, bb)
                        changed = True
        
        return changed
    
    def _has_identical_phi_operands(self, inst: IRInstruction) -> bool:
        """
        Checks if all operands in a phi instruction are identical.
        
        A phi instruction has operands in pairs: (label1, value1, label2, value2, ...)
        We need to check if all values (at odd indices) are identical.
        """
        if inst.opcode != "phi":
            return False
            
        # Get all values from the phi node (every odd-indexed operand)
        values = [inst.operands[i] for i in range(1, len(inst.operands), 2)]
        
        # Check if all values are the same
        if len(values) <= 1:
            return False
            
        first_value = values[0]
        return all(val == first_value for val in values)
        
    def _replace_phi_with_assignment(self, inst: IRInstruction, bb):
        """
        Replaces a phi instruction with a direct assignment.
        
        Since all operands are identical, we can just use the first value.
        """
        # Get the first value from the phi node
        value = inst.operands[1]  # First value in phi node (operands[0] is a label)
        
        # Replace the phi with an assignment
        if isinstance(value, IRLiteral):
            # If the value is a literal, replace phi with store
            new_inst = IRInstruction("store", [value], inst.output)
        elif isinstance(value, IRVariable):
            # If the value is a variable, replace phi with store
            new_inst = IRInstruction("store", [value], inst.output)
        else:
            # Unexpected operand type - leave as is
            return
            
        new_inst.parent = bb
        
        # Replace the phi instruction in the basic block
        idx = bb.instructions.index(inst)
        bb.instructions[idx] = new_inst
class IRInstruction:
    opcode: str
    operands: list
    ret: str

    def __init__(self, opcode, operands, ret=None) -> None:
        self.opcode = opcode
        self.operands = operands
        self.ret = ret

    def __repr__(self) -> str:
        s = ""
        if self.ret:
            s += f"{self.ret} = "
        s += f"{self.opcode} "
        operands = ", ".join([str(op) for op in self.operands])
        return s + operands


class IRBasicBlock:
    label: str
    parent: any  # IRFunction
    instructions: list[IRInstruction]

    def __init__(self, label, parent) -> None:
        self.label = label
        self.parent = parent
        self.instructions = []

    def append_instruction(self, instruction):
        self.instructions.append(instruction)

    def __repr__(self) -> str:
        str = f"{self.label}:\n"
        for instruction in self.instructions:
            str += f"    {instruction}\n"
        return str

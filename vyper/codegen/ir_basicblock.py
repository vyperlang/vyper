class IRInstruction:
    opcode: str
    operands: list

    def __init__(self, opcode, operands) -> None:
        self.opcode = opcode
        self.operands = operands

    def __repr__(self) -> str:
        str = f"{self.opcode} "
        for operand in self.operands:
            str += f"{operand}"
            if self.operands[-1] != operand:
                str += ", "
        return str


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

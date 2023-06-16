class IRDebugInfo:
    line_no: int
    src: str

    def __init__(self, line_no, src) -> None:
        self.line_no = line_no
        self.src = src

    def __repr__(self) -> str:
        src = self.src if self.src else ""
        return f"\t# line {self.line_no}: {src}".expandtabs(20)


class IRInstruction:
    opcode: str
    operands: list
    ret: str
    dbg: IRDebugInfo

    def __init__(self, opcode: str, operands: list, ret=None, dbg: IRDebugInfo = None) -> None:
        self.opcode = opcode
        self.operands = operands
        self.ret = ret
        self.dbg = dbg

    def __repr__(self) -> str:
        s = ""
        if self.ret:
            s += f"{self.ret} = "
        s += f"{self.opcode} "
        operands = ", ".join([str(op) for op in self.operands])
        if self.dbg:
            return s + operands + f" {self.dbg}"
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

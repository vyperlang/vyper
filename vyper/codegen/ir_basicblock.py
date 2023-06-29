from typing import Optional, TYPE_CHECKING

TERMINAL_IR_INSTRUCTIONS = [
    "ret",
    "revert",
    "assert",
]

if TYPE_CHECKING:
    from vyper.codegen.ir_function import IRFunction


class IRDebugInfo:
    """
    IRDebugInfo represents debug information in IR, used to annotate IR instructions
    with source code information when printing IR.
    """

    line_no: int
    src: str

    def __init__(self, line_no: int, src: str) -> None:
        self.line_no = line_no
        self.src = src

    def __repr__(self) -> str:
        src = self.src if self.src else ""
        return f"\t# line {self.line_no}: {src}".expandtabs(20)


class IROperant:
    """
    IROperant represents an operand in IR. An operand can be a variable, label, or a constant.
    """

    value: str

    def __init__(self, value: str) -> None:
        assert isinstance(value, str), "value must be a string"
        self.value = value

    def __repr__(self) -> str:
        return self.value


class IRVariable(IROperant):
    """
    IRVariable represents a variable in IR. A variable is a string that starts with a %.
    """

    def __init__(self, value: str) -> None:
        super().__init__(value)


class IRLabel(IROperant):
    """
    IRLabel represents a label in IR. A label is a string that starts with a %.
    """

    is_symbol: bool = False

    def __init__(self, value: str, is_symbol: bool = False) -> None:
        super().__init__(value)
        self.is_symbol = is_symbol


class IRInstruction:
    """
    IRInstruction represents an instruction in IR. Each instruction has an opcode,
    operands, and return value. For example, the following IR instruction:
        %1 = add %0, 1
    has opcode "add", operands ["%0", "1"], and return value "%1".
    """

    opcode: str
    operands: list[IROperant]
    ret: Optional[str]
    dbg: Optional[IRDebugInfo]
    liveness: set[IRVariable]

    def __init__(
        self, opcode: str, operands: list[IROperant], ret: str = None, dbg: IRDebugInfo = None
    ):
        self.opcode = opcode
        self.operands = operands
        self.ret = ret
        self.dbg = dbg
        self.liveness = set()

    def get_label_operands(self) -> list[IRLabel]:
        """
        Get all labels in instruction.
        """
        return [op for op in self.operands if isinstance(op, IRLabel)]

    def get_input_operands(self) -> list[IROperant]:
        """
        Get all input operands in instruction.
        """
        return [op for op in self.operands if isinstance(op, IRVariable)]

    def get_output_operands(self) -> list[IROperant]:
        return [self.ret]

    def __repr__(self) -> str:
        s = ""
        if self.ret:
            s += f"{self.ret} = "
        s += f"{self.opcode} "
        operands = ", ".join(
            [(f"label %{op}" if isinstance(op, IRLabel) else str(op)) for op in self.operands]
        )
        s += operands

        if self.dbg:
            return s + f" {self.dbg}"

        if self.liveness:
            return f"{s: <30} # {self.liveness}"

        return s


class IRBasicBlock:
    """
    IRBasicBlock represents a basic block in IR. Each basic block has a label and
    a list of instructions, while belonging to a function.

    The following IR code:
        %1 = add %0, 1
        %2 = mul %1, 2
    is represented as:
        bb = IRBasicBlock("bb", function)
        bb.append_instruction(IRInstruction("add", ["%0", "1"], "%1"))
        bb.append_instruction(IRInstruction("mul", ["%1", "2"], "%2"))

    The label of a basic block is used to refer to it from other basic blocks in order
    to branch to it.

    The parent of a basic block is the function it belongs to.

    The instructions of a basic block are executed sequentially, and the last instruction
    of a basic block is always a terminator instruction, which is used to branch to other
    basic blocks.
    """

    label: IRLabel
    parent: "IRFunction"
    instructions: list[IRInstruction]
    in_set: set["IRBasicBlock"]
    out_set: set["IRBasicBlock"]
    out_vars: set[IRVariable]

    def __init__(self, label: IRLabel, parent: "IRFunction") -> None:
        assert isinstance(label, IRLabel), "label must be an IRLabel"
        self.label = label
        self.parent = parent
        self.instructions = []
        self.in_set = set()
        self.out_set = set()
        self.out_vars = set()

    def add_in(self, bb: "IRBasicBlock") -> None:
        self.in_set.add(bb)

    def union_in(self, bb_set: set["IRBasicBlock"]) -> None:
        self.in_set = self.in_set.union(bb_set)

    def remove_in(self, bb: "IRBasicBlock") -> None:
        self.in_set.remove(bb)

    def add_out(self, bb: "IRBasicBlock") -> None:
        self.out_set.add(bb)

    def union_out(self, bb_set: set["IRBasicBlock"]) -> None:
        self.out_set = self.out_set.union(bb_set)

    def remove_out(self, bb: "IRBasicBlock") -> None:
        self.out_set.remove(bb)

    @property
    def in_vars(self) -> set[IRVariable]:
        return self.instructions[0].liveness

    def append_instruction(self, instruction: IRInstruction) -> None:
        assert isinstance(instruction, IRInstruction), "instruction must be an IRInstruction"
        self.instructions.append(instruction)

    def is_terminal(self) -> bool:
        """
        Check if the basic block is terminal, i.e. the last instruction is a terminator.
        """
        assert len(self.instructions) > 0, "basic block must have at least one instruction"
        return self.instructions[-1].opcode in TERMINAL_IR_INSTRUCTIONS

    def calculate_liveness(self) -> None:
        """
        Compute liveness of each instruction in basic block.
        """
        for instruction in self.instructions[::-1]:
            self.out_vars = self.out_vars.union(instruction.get_input_operands())
            out = instruction.get_output_operands()[0]
            if out in self.out_vars:
                self.out_vars.remove(out)
            instruction.liveness = self.out_vars.copy()

        print("Liveness:", self.label, "\n", self.in_vars, "\n")

    def __repr__(self) -> str:
        s = f"{repr(self.label)}:  IN={[bb.label for bb in self.in_set]} OUT={[bb.label for bb in self.out_set]} \n"
        for instruction in self.instructions:
            s += f"    {instruction}\n"
        return s

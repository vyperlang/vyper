from enum import Enum
from typing import TYPE_CHECKING, Optional

from vyper.utils import OrderedSet

TERMINAL_IR_INSTRUCTIONS = ["ret", "revert"]
TERMINATOR_IR_INSTRUCTIONS = ["jmp", "jnz", "ret", "return", "revert", "deploy", "stop"]

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


IRValueBaseValue = str | int


class IRValueBase:
    value: IRValueBaseValue
    use_count: int = 0

    def __init__(self, value: IRValueBaseValue) -> None:
        assert isinstance(value, IRValueBaseValue), "value must be an IRValueBaseValue"
        self.value = value
        self.use_count = 0

    @property
    def is_literal(self) -> bool:
        return False

    def __repr__(self) -> str:
        return str(self.value)


class IRLiteral(IRValueBase):
    """
    IRLiteral represents a literal in IR
    """

    def __init__(self, value: IRValueBaseValue) -> None:
        super().__init__(value)
        self.use_count = 0

    @property
    def is_literal(self) -> bool:
        return True


class IRVariable(IRValueBase):
    """
    IRVariable represents a variable in IR. A variable is a string that starts with a %.
    """

    offset: int = 0
    MemType = Enum("MemType", ["OPERAND_STACK", "MEMORY"])
    mem_type: MemType = MemType.OPERAND_STACK
    mem_addr: int = -1

    def __init__(
        self, value: IRValueBaseValue, mem_type: MemType = MemType.OPERAND_STACK, mem_addr: int = -1
    ) -> None:
        if isinstance(value, IRLiteral):
            value = value.value
        super().__init__(value)
        self.offset = 0
        self.mem_type = mem_type
        self.mem_addr = mem_addr


class IRLabel(IRValueBase):
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
    volatile: bool
    operands: list[IRValueBase]
    ret: Optional[IRValueBase]
    dbg: Optional[IRDebugInfo]
    liveness: set[IRVariable]
    parent: Optional["IRBasicBlock"]
    fen: int
    annotation: Optional[str]

    def __init__(
        self,
        opcode: str,
        operands: list[IRValueBase],
        ret: IRValueBase = None,
        dbg: IRDebugInfo = None,
    ):
        self.opcode = opcode
        self.volatile = opcode in [
            "param",
            "alloca",
            "call",
            "staticcall",
            "invoke",
            "sload",
            "sstore",
            "assert",
            "mstore",
            "mload",
            "calldatacopy",
            "codecopy",
            "dloadbytes",
            "dload",
        ]
        self.operands = [op if isinstance(op, IRValueBase) else IRValueBase(op) for op in operands]
        self.ret = ret if isinstance(ret, IRValueBase) else IRValueBase(ret) if ret else None
        self.dbg = dbg
        self.liveness = set()
        self.parent = None
        self.fen = -1
        self.annotation = None

    def get_label_operands(self) -> list[IRLabel]:
        """
        Get all labels in instruction.
        """
        return [op for op in self.operands if isinstance(op, IRLabel)]

    def get_non_label_operands(self) -> list[IRValueBase]:
        """
        Get all input operands in instruction.
        """
        return [op for op in self.operands if not isinstance(op, IRLabel)]

    def get_input_operands(self) -> list[IRValueBase]:
        """
        Get all input operands for instruction.
        """
        return [op for op in self.operands if isinstance(op, IRVariable)]

    def get_output_operands(self) -> list[IRValueBase]:
        return [self.ret] if self.ret else []

    def update_operands(self, replacements: dict) -> None:
        """
        Update operands with replacements.
        """
        for i, operand in enumerate(self.operands):
            if operand in replacements.keys():
                self.operands[i] = replacements[operand]

    def __repr__(self) -> str:
        s = ""
        if self.ret:
            s += f"{self.ret} = "
        opcode = f"{self.opcode} " if self.opcode != "store" else ""
        s += opcode
        operands = ", ".join(
            [(f"label %{op}" if isinstance(op, IRLabel) else str(op)) for op in self.operands[::-1]]
        )
        s += operands

        if self.dbg:
            return s + f" {self.dbg}"

        if self.annotation:
            s += f" <{self.annotation}>"

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
    in_set: OrderedSet["IRBasicBlock"]
    out_set: OrderedSet["IRBasicBlock"]
    out_vars: OrderedSet[IRVariable]
    phi_vars: dict[str, IRVariable]

    def __init__(self, label: IRLabel, parent: "IRFunction") -> None:
        assert isinstance(label, IRLabel), "label must be an IRLabel"
        self.label = label
        self.parent = parent
        self.instructions = []
        self.in_set = OrderedSet()
        self.out_set = OrderedSet()
        self.out_vars = OrderedSet()
        self.phi_vars = {}

    def add_in(self, bb: "IRBasicBlock") -> None:
        self.in_set.add(bb)

    def union_in(self, bb_set: OrderedSet["IRBasicBlock"]) -> None:
        self.in_set = self.in_set.union(bb_set)

    def remove_in(self, bb: "IRBasicBlock") -> None:
        self.in_set.remove(bb)

    def add_out(self, bb: "IRBasicBlock") -> None:
        self.out_set.add(bb)

    def union_out(self, bb_set: OrderedSet["IRBasicBlock"]) -> None:
        self.out_set = self.out_set.union(bb_set)

    def remove_out(self, bb: "IRBasicBlock") -> None:
        self.out_set.remove(bb)

    def in_vars_for(self, bb: "IRBasicBlock" = None) -> set[IRVariable]:
        liveness = self.instructions[0].liveness.copy()

        if bb:
            for inst in self.instructions:
                if inst.opcode == "select":
                    if inst.operands[0] == bb.label:
                        liveness.add(inst.operands[1])
                        if inst.operands[3] in liveness:
                            liveness.remove(inst.operands[3])
                    if inst.operands[2] == bb.label:
                        liveness.add(inst.operands[3])
                        if inst.operands[1] in liveness:
                            liveness.remove(inst.operands[1])

        return liveness

    @property
    def is_reachable(self) -> bool:
        return len(self.in_set) > 0

    def append_instruction(self, instruction: IRInstruction) -> None:
        assert isinstance(instruction, IRInstruction), "instruction must be an IRInstruction"
        instruction.parent = self
        self.instructions.append(instruction)

    def insert_instruction(self, instruction: IRInstruction, index: int) -> None:
        assert isinstance(instruction, IRInstruction), "instruction must be an IRInstruction"
        instruction.parent = self
        self.instructions.insert(index, instruction)

    def clear_instructions(self) -> None:
        self.instructions = []

    def update_operands(self, replacements: dict) -> None:
        """
        Update operands with replacements.
        """
        for instruction in self.instructions:
            instruction.update_operands(replacements)

    def is_terminal(self) -> bool:
        """
        Check if the basic block is terminal, i.e. the last instruction is a terminator.
        """
        assert len(self.instructions) > 0, "basic block must have at least one instruction"
        return self.instructions[-1].opcode in TERMINAL_IR_INSTRUCTIONS

    @property
    def is_terminated(self) -> bool:
        """
        Check if the basic block is terminal, i.e. the last instruction is a terminator.
        """
        if len(self.instructions) == 0:
            return False
        return self.instructions[-1].opcode in TERMINATOR_IR_INSTRUCTIONS

    def calculate_liveness(self) -> None:
        """
        Compute liveness of each instruction in the basic block.
        """
        liveness = self.out_vars.copy()
        for instruction in self.instructions[::-1]:
            ops = instruction.get_input_operands()
            liveness = liveness.union(OrderedSet.fromkeys(ops))
            out = (
                instruction.get_output_operands()[0]
                if len(instruction.get_output_operands()) > 0
                else None
            )
            if out in liveness:
                liveness.remove(out)
            instruction.liveness = liveness

    def get_liveness(self) -> set[IRVariable]:
        """
        Get liveness of basic block.
        """
        return self.instructions[0].liveness

    def __repr__(self) -> str:
        s = (
            f"{repr(self.label)}:  IN={[bb.label for bb in self.in_set]}"
            f" OUT={[bb.label for bb in self.out_set]} \n"
        )
        for instruction in self.instructions:
            s += f"    {instruction}\n"
        return s

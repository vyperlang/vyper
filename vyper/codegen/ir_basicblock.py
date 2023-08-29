from typing import TYPE_CHECKING, Optional
from enum import Enum

TERMINAL_IR_INSTRUCTIONS = ["ret", "revert", "assert"]
TERMINATOR_IR_INSTRUCTIONS = ["jmp", "jnz", "ret", "revert"]

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
        self.use_count = 1

    @property
    def is_literal(self) -> bool:
        return True


class IRVariable(IRValueBase):
    """
    IRVariable represents a variable in IR. A variable is a string that starts with a %.
    """

    MemType = Enum("MemType", ["OPERAND_STACK", "MEMORY"])
    mem_type: MemType = MemType.OPERAND_STACK
    mem_addr: int = -1

    def __init__(
        self, value: IRValueBaseValue, mem_type: MemType = MemType.OPERAND_STACK, mem_addr: int = -1
    ) -> None:
        super().__init__(value)
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


IROperandTarget = IRLiteral | IRVariable | IRLabel


class IROperand:
    """
    IROperand represents an operand of an IR instuction. An operand can be a variable, label, or a constant.
    """

    target: IRValueBase
    address_access: bool = False
    address_offset: int = 0
    use_count: int = 0

    def __init__(
        self, target: IRValueBase, address_access: bool = False, address_offset: int = 0
    ) -> None:
        assert isinstance(target, IRValueBase), "value must be an IRValueBase"
        if address_access:
            assert (
                isinstance(target, IRVariable) and target.mem_type == IRVariable.MemType.MEMORY
            ), "address access can only be used for memory variables"
            self.address_access = address_access
            self.address_offset = address_offset
        self.target = target

    def is_targeting(self, target: IRValueBase) -> bool:
        return self.target.value == target.value

    @property
    def value(self) -> IRValueBaseValue:
        return self.target.value

    @property
    def addr(self) -> int:
        assert self.is_variable, "address can only be accessed for variables"
        target: IRVariable = self.target
        return target.mem_addr + self.address_offset

    @property
    def is_literal(self) -> bool:
        return isinstance(self.target, IRLiteral)

    @property
    def is_variable(self) -> bool:
        return isinstance(self.target, IRVariable)

    @property
    def is_label(self) -> bool:
        return isinstance(self.target, IRLabel)

    def __repr__(self) -> str:
        offsetStr = f"{self.address_offset:+}" if self.address_offset else ""
        return f"{'ptr ' if self.address_access else ''}{self.target}{offsetStr}"


class IRInstruction:
    """
    IRInstruction represents an instruction in IR. Each instruction has an opcode,
    operands, and return value. For example, the following IR instruction:
        %1 = add %0, 1
    has opcode "add", operands ["%0", "1"], and return value "%1".
    """

    opcode: str
    operands: list[IROperand]
    ret: Optional[IROperand]
    dbg: Optional[IRDebugInfo]
    liveness: set[IRVariable]
    parent: Optional["IRBasicBlock"]
    fen: int

    def __init__(
        self,
        opcode: str,
        operands: list[IROperand | IRValueBase],
        ret: IROperand = None,
        dbg: IRDebugInfo = None,
    ):
        self.opcode = opcode
        self.operands = [op if isinstance(op, IROperand) else IROperand(op) for op in operands]
        self.ret = ret if isinstance(ret, IROperand) else IROperand(ret) if ret else None
        self.dbg = dbg
        self.liveness = set()
        self.parent = None
        self.fen = -1

    def get_label_operands(self) -> list[IRLabel]:
        """
        Get all labels in instruction.
        """
        return [op for op in self.operands if op.is_label]

    def get_input_operands(self) -> list[IROperand]:
        """
        Get all input operands in instruction.
        """
        return [op for op in self.operands if not op.is_label]

    def get_input_variables(self) -> list[IRVariable]:
        """
        Get all input variables in instruction.
        """
        return [op.target for op in self.operands if op.is_variable]

    def get_output_operands(self) -> list[IROperand]:
        return [self.ret] if self.ret else []

    def get_use_count_correction(self, op: IROperand) -> int:
        use_count_correction = 0
        for _, phi in self.parent.phi_vars.items():
            if phi.value == op.target.value:
                use_count_correction += 1
        return use_count_correction

    def __repr__(self) -> str:
        s = ""
        if self.ret:
            s += f"{self.ret} = "
        s += f"{self.opcode} "
        operands = ", ".join(
            [(f"label %{op}" if op.is_label else str(op)) for op in self.operands[::-1]]
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
    phi_vars: dict[str, IRVariable]

    def __init__(self, label: IRLabel, parent: "IRFunction") -> None:
        assert isinstance(label, IRLabel), "label must be an IRLabel"
        self.label = label
        self.parent = parent
        self.instructions = []
        self.in_set = set()
        self.out_set = set()
        self.out_vars = set()
        self.phi_vars = {}

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

    def in_vars_for(self, bb: "IRBasicBlock" = None) -> set[IRVariable]:
        liveness = self.instructions[0].liveness.copy()

        if bb:
            for inst in self.instructions:
                if inst.opcode == "select":
                    if inst.operands[0].target == bb.label:
                        liveness.add(inst.operands[1].target)
                        if inst.operands[3].target in liveness:
                            liveness.remove(inst.operands[3].target)
                    if inst.operands[2].target == bb.label:
                        liveness.add(inst.operands[3].target)
                        if inst.operands[1].target in liveness:
                            liveness.remove(inst.operands[1].target)

        return liveness

    @property
    def is_reachable(self) -> bool:
        return len(self.in_set) > 0

    def append_instruction(self, instruction: IRInstruction) -> None:
        assert isinstance(instruction, IRInstruction), "instruction must be an IRInstruction"
        instruction.parent = self
        self.instructions.append(instruction)

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
            liveness = liveness.union(instruction.get_input_variables())
            out = (
                instruction.get_output_operands()[0].target
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
        return self.instructions[-1].liveness

    def __repr__(self) -> str:
        s = (
            f"{repr(self.label)}:  IN={[bb.label for bb in self.in_set]}"
            f" OUT={[bb.label for bb in self.out_set]} \n"
        )
        for instruction in self.instructions:
            s += f"    {instruction}\n"
        return s

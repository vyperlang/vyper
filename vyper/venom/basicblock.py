from enum import Enum
from typing import TYPE_CHECKING, Optional

from vyper.exceptions import CompilerPanic
from vyper.utils import OrderedSet

# instructions which can terminate a basic block
BB_TERMINATORS = ["jmp", "jnz", "ret", "return", "revert", "deploy", "stop"]

VOLATILE_INSTRUCTIONS = [
    "param",
    "alloca",
    "call",
    "staticcall",
    "invoke",
    "sload",
    "sstore",
    "iload",
    "istore",
    "assert",
    "mstore",
    "mload",
    "calldatacopy",
    "codecopy",
    "dloadbytes",
    "dload",
    "return",
    "ret",
    "jmp",
    "jnz",
]


if TYPE_CHECKING:
    from vyper.venom.function import IRFunction


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

    @property
    def is_literal(self) -> bool:
        return True


MemType = Enum("MemType", ["OPERAND_STACK", "MEMORY"])


class IRVariable(IRValueBase):
    """
    IRVariable represents a variable in IR. A variable is a string that starts with a %.
    """

    offset: int = 0
    mem_type: MemType = MemType.OPERAND_STACK
    mem_addr: int = -1  # REVIEW should this be None?

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

    # is_symbol is used to indicate if the label came from upstream
    # (like a function name, try to preserve it in optimization passes)
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
    output: Optional[IRValueBase]
    # set of live variables at this instruction
    liveness: OrderedSet[IRVariable]
    dup_requirements: OrderedSet[IRVariable]
    parent: Optional["IRBasicBlock"]
    fence_id: int
    annotation: Optional[str]

    def __init__(self, opcode: str, operands: list[IRValueBase], output: IRValueBase = None):
        self.opcode = opcode
        self.volatile = opcode in VOLATILE_INSTRUCTIONS
        self.operands = [op if isinstance(op, IRValueBase) else IRValueBase(op) for op in operands]
        self.output = output if isinstance(output, IRValueBase) else IRValueBase(output) if output else None
        self.liveness = OrderedSet()
        self.dup_requirements = OrderedSet()
        self.parent = None
        self.fence_id = -1
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

    def get_inputs(self) -> list[IRValueBase]:
        """
        Get all input operands for instruction.
        """
        return [op for op in self.operands if isinstance(op, IRVariable)]

    def get_outputs(self) -> list[IRVariable]:
        return [self.output] if self.output else []

    def replace_operands(self, replacements: dict) -> None:
        """
        Update operands with replacements.
        replacements are represented using a dict: "key" is replaced by "value".
        """
        for i, operand in enumerate(self.operands):
            if operand in replacements:
                self.operands[i] = replacements[operand]

    def __repr__(self) -> str:
        s = ""
        if self.output:
            s += f"{self.output} = "
        opcode = f"{self.opcode} " if self.opcode != "store" else ""
        s += opcode
        operands = ", ".join(
            [
                (f"label %{op}" if isinstance(op, IRLabel) else str(op))
                for op in reversed(self.operands)
            ]
        )
        s += operands

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

    The label of a basic block is used to refer to it from other basic blocks
    in order to branch to it.

    The parent of a basic block is the function it belongs to.

    The instructions of a basic block are executed sequentially, and the last
    instruction of a basic block is always a terminator instruction, which is
    used to branch to other basic blocks.
    """

    label: IRLabel
    parent: "IRFunction"
    instructions: list[IRInstruction]
    # basic blocks which can jump to this basic block
    cfg_in: OrderedSet["IRBasicBlock"]
    # basic blocks which this basic block can jump to
    cfg_out: OrderedSet["IRBasicBlock"]
    # stack items which this basic block produces
    out_vars: OrderedSet[IRVariable]

    def __init__(self, label: IRLabel, parent: "IRFunction") -> None:
        assert isinstance(label, IRLabel), "label must be an IRLabel"
        self.label = label
        self.parent = parent
        self.instructions = []
        self.cfg_in = OrderedSet()
        self.cfg_out = OrderedSet()
        self.out_vars = OrderedSet()

    def add_cfg_in(self, bb: "IRBasicBlock") -> None:
        self.cfg_in.add(bb)

    def union_cfg_in(self, bb_set: OrderedSet["IRBasicBlock"]) -> None:
        self.cfg_in = self.cfg_in.union(bb_set)

    def remove_cfg_in(self, bb: "IRBasicBlock") -> None:
        self.cfg_in.remove(bb)

    def add_cfg_out(self, bb: "IRBasicBlock") -> None:
        self.cfg_out.add(bb)

    def union_cfg_out(self, bb_set: OrderedSet["IRBasicBlock"]) -> None:
        self.cfg_out = self.cfg_out.union(bb_set)

    def remove_cfg_out(self, bb: "IRBasicBlock") -> None:
        self.cfg_out.remove(bb)

    # calculate the input variables into self from source
    def in_vars_from(self, source: "IRBasicBlock") -> OrderedSet[IRVariable]:
        liveness = self.instructions[0].liveness.copy()
        assert isinstance(liveness, OrderedSet)

        for inst in self.instructions:
            if inst.opcode == "phi":
                # we arbitrarily choose one of the arguments to be in the
                # live variables set (dependent on how we traversed into this
                # basic block). the argument will be replaced by the destination
                # operand during instruction selection.
                # for instance, `%56 = phi %label1 %12 %label2 %14`
                # will arbitrarily choose either %12 or %14 to be in the liveness
                # set, and then during instruction selection, after this instruction,
                # %12 will be replaced by %56 in the liveness set
                source1, source2 = inst.operands[0], inst.operands[2]
                phi1, phi2 = inst.operands[1], inst.operands[3]
                if source.label == source1:
                    liveness.add(phi1)
                    if phi2 in liveness:
                        liveness.remove(phi2)
                elif source.label == source2:
                    liveness.add(phi2)
                    if phi1 in liveness:
                        liveness.remove(phi1)
                else:
                    # bad path into this phi node
                    raise CompilerPanic(f"unreachable: {inst}")

        return liveness

    @property
    def is_reachable(self) -> bool:
        return len(self.cfg_in) > 0

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

    def replace_operands(self, replacements: dict) -> None:
        """
        Update operands with replacements.
        """
        for instruction in self.instructions:
            instruction.replace_operands(replacements)

    @property
    def is_terminated(self) -> bool:
        """
        Check if the basic block is terminal, i.e. the last instruction is a terminator.
        """
        # it's ok to return False here, since we use this to check
        # if we can/need to append instructions to the basic block.
        if len(self.instructions) == 0:
            return False
        return self.instructions[-1].opcode in BB_TERMINATORS

    def calculate_liveness(self) -> None:
        """
        Compute liveness of each instruction in the basic block.
        """
        liveness = self.out_vars.copy()
        for instruction in reversed(self.instructions):
            ops = instruction.get_inputs()

            for op in ops:
                if op in liveness:
                    instruction.dup_requirements.add(op)

            liveness = liveness.union(OrderedSet.fromkeys(ops))
            out = instruction.get_outputs()[0] if len(instruction.get_outputs()) > 0 else None
            if out in liveness:
                liveness.remove(out)
            instruction.liveness = liveness

    def copy(self):
        bb = IRBasicBlock(self.label, self.parent)
        bb.instructions = self.instructions.copy()
        bb.cfg_in = self.cfg_in.copy()
        bb.cfg_out = self.cfg_out.copy()
        bb.out_vars = self.out_vars.copy()
        return bb

    def __repr__(self) -> str:
        s = (
            f"{repr(self.label)}:  IN={[bb.label for bb in self.cfg_in]}"
            f" OUT={[bb.label for bb in self.cfg_out]} => {self.out_vars} \n"
        )
        for instruction in self.instructions:
            s += f"    {instruction}\n"
        return s

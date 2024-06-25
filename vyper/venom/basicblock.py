from typing import TYPE_CHECKING, Any, Iterator, Optional, Union

from vyper.codegen.ir_node import IRnode
from vyper.utils import OrderedSet

# instructions which can terminate a basic block
BB_TERMINATORS = frozenset(["jmp", "djmp", "jnz", "ret", "return", "stop", "exit"])

VOLATILE_INSTRUCTIONS = frozenset(
    [
        "param",
        "call",
        "staticcall",
        "delegatecall",
        "create",
        "create2",
        "invoke",
        "sload",
        "sstore",
        "iload",
        "istore",
        "tload",
        "tstore",
        "assert",
        "assert_unreachable",
        "mstore",
        "mload",
        "calldatacopy",
        "mcopy",
        "extcodecopy",
        "returndatacopy",
        "codecopy",
        "dloadbytes",
        "dload",
        "return",
        "ret",
        "jmp",
        "jnz",
        "djmp",
        "log",
        "selfdestruct",
        "invalid",
        "revert",
        "assert",
        "assert_unreachable",
        "stop",
        "exit",
    ]
)

NO_OUTPUT_INSTRUCTIONS = frozenset(
    [
        "mstore",
        "sstore",
        "istore",
        "tstore",
        "dloadbytes",
        "calldatacopy",
        "mcopy",
        "returndatacopy",
        "codecopy",
        "extcodecopy",
        "return",
        "ret",
        "revert",
        "assert",
        "assert_unreachable",
        "selfdestruct",
        "stop",
        "invalid",
        "invoke",
        "jmp",
        "djmp",
        "jnz",
        "log",
        "exit",
    ]
)

assert VOLATILE_INSTRUCTIONS.issuperset(NO_OUTPUT_INSTRUCTIONS), (
    NO_OUTPUT_INSTRUCTIONS - VOLATILE_INSTRUCTIONS
)

CFG_ALTERING_INSTRUCTIONS = frozenset(["jmp", "djmp", "jnz"])

if TYPE_CHECKING:
    from vyper.venom.function import IRFunction


class IRDebugInfo:
    """
    IRDebugInfo represents debug information in IR, used to annotate IR
    instructions with source code information when printing IR.
    """

    line_no: int
    src: str

    def __init__(self, line_no: int, src: str) -> None:
        self.line_no = line_no
        self.src = src

    def __repr__(self) -> str:
        src = self.src if self.src else ""
        return f"\t# line {self.line_no}: {src}".expandtabs(20)


class IROperand:
    """
    IROperand represents an IR operand. An operand is anything that can be
    operated by instructions. It can be a literal, a variable, or a label.
    """

    value: Any

    @property
    def name(self) -> str:
        return self.value

    def __hash__(self) -> int:
        return hash(self.value)

    def __eq__(self, other) -> bool:
        if not isinstance(other, type(self)):
            return False
        return self.value == other.value

    def __repr__(self) -> str:
        return str(self.value)


class IRLiteral(IROperand):
    """
    IRLiteral represents a literal in IR
    """

    value: int

    def __init__(self, value: int) -> None:
        assert isinstance(value, int), "value must be an int"
        self.value = value


class IRVariable(IROperand):
    """
    IRVariable represents a variable in IR. A variable is a string that starts with a %.
    """

    value: str

    def __init__(self, value: str, version: Optional[str | int] = None) -> None:
        assert isinstance(value, str)
        assert ":" not in value, "Variable name cannot contain ':'"
        if version:
            assert isinstance(value, str) or isinstance(value, int), "value must be an str or int"
            value = f"{value}:{version}"
        if value[0] != "%":
            value = f"%{value}"
        self.value = value

    @property
    def name(self) -> str:
        return self.value.split(":")[0]

    @property
    def version(self) -> int:
        if ":" not in self.value:
            return 0
        return int(self.value.split(":")[1])


class IRLabel(IROperand):
    """
    IRLabel represents a label in IR. A label is a string that starts with a %.
    """

    # is_symbol is used to indicate if the label came from upstream
    # (like a function name, try to preserve it in optimization passes)
    is_symbol: bool = False
    value: str

    def __init__(self, value: str, is_symbol: bool = False) -> None:
        assert isinstance(value, str), "value must be an str"
        self.value = value
        self.is_symbol = is_symbol

    def __eq__(self, other):
        # no need for is_symbol to participate in equality
        return super().__eq__(other)

    def __hash__(self):
        # __hash__ is required when __eq__ is overridden --
        # https://docs.python.org/3/reference/datamodel.html#object.__hash__
        return super().__hash__()


class IRInstruction:
    """
    IRInstruction represents an instruction in IR. Each instruction has an opcode,
    operands, and return value. For example, the following IR instruction:
        %1 = add %0, 1
    has opcode "add", operands ["%0", "1"], and return value "%1".

    Convention: the rightmost value is the top of the stack.
    """

    opcode: str
    operands: list[IROperand]
    output: Optional[IROperand]
    # set of live variables at this instruction
    liveness: OrderedSet[IRVariable]
    dup_requirements: OrderedSet[IRVariable]
    parent: "IRBasicBlock"
    fence_id: int
    annotation: Optional[str]
    ast_source: Optional[IRnode]
    error_msg: Optional[str]

    def __init__(
        self,
        opcode: str,
        operands: list[IROperand] | Iterator[IROperand],
        output: Optional[IROperand] = None,
    ):
        assert isinstance(opcode, str), "opcode must be an str"
        assert isinstance(operands, list | Iterator), "operands must be a list"
        self.opcode = opcode
        self.operands = list(operands)  # in case we get an iterator
        self.output = output
        self.liveness = OrderedSet()
        self.dup_requirements = OrderedSet()
        self.fence_id = -1
        self.annotation = None
        self.ast_source = None
        self.error_msg = None

    @property
    def is_volatile(self) -> bool:
        return self.opcode in VOLATILE_INSTRUCTIONS

    @property
    def is_bb_terminator(self) -> bool:
        return self.opcode in BB_TERMINATORS

    def get_label_operands(self) -> Iterator[IRLabel]:
        """
        Get all labels in instruction.
        """
        return (op for op in self.operands if isinstance(op, IRLabel))

    def get_non_label_operands(self) -> Iterator[IROperand]:
        """
        Get input operands for instruction which are not labels
        """
        return (op for op in self.operands if not isinstance(op, IRLabel))

    def get_input_variables(self) -> Iterator[IRVariable]:
        """
        Get all input operands for instruction.
        """
        return (op for op in self.operands if isinstance(op, IRVariable))

    def get_outputs(self) -> list[IROperand]:
        """
        Get the output item for an instruction.
        (Currently all instructions output at most one item, but write
        it as a list to be generic for the future)
        """
        return [self.output] if self.output else []

    def replace_operands(self, replacements: dict) -> None:
        """
        Update operands with replacements.
        replacements are represented using a dict: "key" is replaced by "value".
        """
        for i, operand in enumerate(self.operands):
            if operand in replacements:
                self.operands[i] = replacements[operand]

    def replace_label_operands(self, replacements: dict) -> None:
        """
        Update label operands with replacements.
        replacements are represented using a dict: "key" is replaced by "value".
        """
        replacements = {k.value: v for k, v in replacements.items()}
        for i, operand in enumerate(self.operands):
            if isinstance(operand, IRLabel) and operand.value in replacements:
                self.operands[i] = replacements[operand.value]

    @property
    def phi_operands(self) -> Iterator[tuple[IRLabel, IROperand]]:
        """
        Get phi operands for instruction.
        """
        assert self.opcode == "phi", "instruction must be a phi"
        for i in range(0, len(self.operands), 2):
            label = self.operands[i]
            var = self.operands[i + 1]
            assert isinstance(label, IRLabel), "phi operand must be a label"
            assert isinstance(
                var, (IRVariable, IRLiteral)
            ), "phi operand must be a variable or literal"
            yield label, var

    def remove_phi_operand(self, label: IRLabel) -> None:
        """
        Remove a phi operand from the instruction.
        """
        assert self.opcode == "phi", "instruction must be a phi"
        for i in range(0, len(self.operands), 2):
            if self.operands[i] == label:
                del self.operands[i : i + 2]
                return

    def get_ast_source(self) -> Optional[IRnode]:
        if self.ast_source:
            return self.ast_source
        idx = self.parent.instructions.index(self)
        for inst in reversed(self.parent.instructions[:idx]):
            if inst.ast_source:
                return inst.ast_source
        return self.parent.parent.ast_source

    def __repr__(self) -> str:
        s = ""
        if self.output:
            s += f"{self.output} = "
        opcode = f"{self.opcode} " if self.opcode != "store" else ""
        s += opcode
        operands = self.operands
        if opcode not in ["jmp", "jnz", "invoke"]:
            operands = reversed(operands)  # type: ignore
        s += ", ".join(
            [(f"label %{op}" if isinstance(op, IRLabel) else str(op)) for op in operands]
        )

        if self.annotation:
            s += f" <{self.annotation}>"

        if self.liveness:
            return f"{s: <30} # {self.liveness}"

        return s


def _ir_operand_from_value(val: Any) -> IROperand:
    if isinstance(val, IROperand):
        return val

    assert isinstance(val, int), val
    return IRLiteral(val)


class IRBasicBlock:
    """
    IRBasicBlock represents a basic block in IR. Each basic block has a label and
    a list of instructions, while belonging to a function.

    The following IR code:
        %1 = add %0, 1
        %2 = mul %1, 2
    is represented as:
        bb = IRBasicBlock("bb", function)
        r1 = bb.append_instruction("add", "%0", "1")
        r2 = bb.append_instruction("mul", r1, "2")

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

    reachable: OrderedSet["IRBasicBlock"]
    is_reachable: bool = False

    def __init__(self, label: IRLabel, parent: "IRFunction") -> None:
        assert isinstance(label, IRLabel), "label must be an IRLabel"
        self.label = label
        self.parent = parent
        self.instructions = []
        self.cfg_in = OrderedSet()
        self.cfg_out = OrderedSet()
        self.out_vars = OrderedSet()
        self.reachable = OrderedSet()
        self.is_reachable = False

    def add_cfg_in(self, bb: "IRBasicBlock") -> None:
        self.cfg_in.add(bb)

    def remove_cfg_in(self, bb: "IRBasicBlock") -> None:
        assert bb in self.cfg_in
        self.cfg_in.remove(bb)

    def add_cfg_out(self, bb: "IRBasicBlock") -> None:
        # malformed: jnz condition label1 label1
        # (we could handle but it makes a lot of code easier
        # if we have this assumption)
        self.cfg_out.add(bb)

    def remove_cfg_out(self, bb: "IRBasicBlock") -> None:
        assert bb in self.cfg_out
        self.cfg_out.remove(bb)

    def append_instruction(
        self, opcode: str, *args: Union[IROperand, int], ret: IRVariable = None
    ) -> Optional[IRVariable]:
        """
        Append an instruction to the basic block

        Returns the output variable if the instruction supports one
        """
        assert not self.is_terminated, self

        if ret is None:
            ret = self.parent.get_next_variable() if opcode not in NO_OUTPUT_INSTRUCTIONS else None

        # Wrap raw integers in IRLiterals
        inst_args = [_ir_operand_from_value(arg) for arg in args]

        inst = IRInstruction(opcode, inst_args, ret)
        inst.parent = self
        inst.ast_source = self.parent.ast_source
        inst.error_msg = self.parent.error_msg
        self.instructions.append(inst)
        return ret

    def append_invoke_instruction(
        self, args: list[IROperand | int], returns: bool
    ) -> Optional[IRVariable]:
        """
        Append an invoke to the basic block
        """
        assert not self.is_terminated, self
        ret = None
        if returns:
            ret = self.parent.get_next_variable()

        # Wrap raw integers in IRLiterals
        inst_args = [_ir_operand_from_value(arg) for arg in args]

        assert isinstance(inst_args[0], IRLabel), "Invoked non label"

        inst = IRInstruction("invoke", inst_args, ret)
        inst.parent = self
        inst.ast_source = self.parent.ast_source
        inst.error_msg = self.parent.error_msg
        self.instructions.append(inst)
        return ret

    def insert_instruction(self, instruction: IRInstruction, index: Optional[int] = None) -> None:
        assert isinstance(instruction, IRInstruction), "instruction must be an IRInstruction"

        if index is None:
            assert not self.is_terminated, self
            index = len(self.instructions)
        instruction.parent = self
        instruction.ast_source = self.parent.ast_source
        instruction.error_msg = self.parent.error_msg
        self.instructions.insert(index, instruction)

    def remove_instruction(self, instruction: IRInstruction) -> None:
        assert isinstance(instruction, IRInstruction), "instruction must be an IRInstruction"
        self.instructions.remove(instruction)

    def clear_instructions(self) -> None:
        self.instructions = []

    def replace_operands(self, replacements: dict) -> None:
        """
        Update operands with replacements.
        """
        for instruction in self.instructions:
            instruction.replace_operands(replacements)

    def get_assignments(self):
        """
        Get all assignments in basic block.
        """
        return [inst.output for inst in self.instructions if inst.output]

    def get_uses(self) -> dict[IRVariable, OrderedSet[IRInstruction]]:
        uses: dict[IRVariable, OrderedSet[IRInstruction]] = {}
        for inst in self.instructions:
            for op in inst.get_input_variables():
                if op not in uses:
                    uses[op] = OrderedSet()
                uses[op].add(inst)
        return uses

    @property
    def is_empty(self) -> bool:
        """
        Check if the basic block is empty, i.e. it has no instructions.
        """
        return len(self.instructions) == 0

    @property
    def is_terminated(self) -> bool:
        """
        Check if the basic block is terminal, i.e. the last instruction is a terminator.
        """
        # it's ok to return False here, since we use this to check
        # if we can/need to append instructions to the basic block.
        if len(self.instructions) == 0:
            return False
        return self.instructions[-1].is_bb_terminator

    @property
    def is_terminal(self) -> bool:
        """
        Check if the basic block is terminal.
        """
        return len(self.cfg_out) == 0

    @property
    def liveness_in_vars(self) -> OrderedSet[IRVariable]:
        for inst in self.instructions:
            if inst.opcode != "phi":
                return inst.liveness
        return OrderedSet()

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
            f" OUT={[bb.label for bb in self.cfg_out]} => {self.out_vars}\n"
        )
        for instruction in self.instructions:
            s += f"    {str(instruction).strip()}\n"
        return s

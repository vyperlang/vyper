from vyper.codegen.ir_basicblock import IRBasicBlock


class IRFunctionBase:
    name: str  # symbol name
    args: list

    def __init__(self, name, args=[]) -> None:
        self.name = name
        self.args = args


class IRFunction(IRFunctionBase):
    basic_blocks: list
    last_label: int
    last_variable: int

    def __init__(self, name) -> None:
        super().__init__(name)
        self.basic_blocks = []
        self.last_label = 0
        self.last_variable = 0

        self.append_basic_block(IRBasicBlock(name, self))

    def append_basic_block(self, bb):
        """
        Append basic block to function.
        """
        assert isinstance(bb, IRBasicBlock), f"append_basic_block takes IRBasicBlock, got '{bb}'"
        self.basic_blocks.append(bb)

    def get_basic_block(self, label=None) -> IRBasicBlock:
        """
        Get basic block by label.
        If label is None, return the last basic block.
        """
        if label is None:
            return self.basic_blocks[-1]
        for bb in self.basic_blocks:
            if bb.label == label:
                return bb
        return None

    def get_next_label(self) -> str:
        self.last_label += 1
        return f"{self.last_label}"

    def get_next_variable(self) -> str:
        self.last_variable += 1
        return f"%{self.last_variable}"

    def get_last_variable(self) -> str:
        return f"%{self.last_variable}"

    def __repr__(self) -> str:
        str = f"IRFunction: {self.name}\n"
        for bb in self.basic_blocks:
            str += f"{bb}\n"
        return str


class IRFunctionIntrinsic(IRFunctionBase):
    """
    Intrinsic function, to represent sertain instructions of EVM that
    are directly emmitted by the compiler frontend to the s-expression IR
    """

    def __repr__(self) -> str:
        args = ", ".join([str(arg) for arg in self.args])
        return f"{self.name}({args})"

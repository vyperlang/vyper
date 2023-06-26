from typing import Optional
from vyper.codegen.ir_basicblock import IRBasicBlock


class IRFunctionBase:
    """
    Base class for IRFunction and IRFunctionIntrinsic
    """

    name: str  # symbol name
    args: list

    def __init__(self, name: str, args: list = []) -> None:
        self.name = name
        self.args = args


class IRFunction(IRFunctionBase):
    """
    Function that contains basic blocks.
    """

    basic_blocks: list
    last_label: int
    last_variable: int

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.basic_blocks = []
        self.last_label = 0
        self.last_variable = 0

        self.append_basic_block(IRBasicBlock(name, self))

    def append_basic_block(self, bb: IRBasicBlock) -> None:
        """
        Append basic block to function.
        If the last basic block is empty it replaces it. Therefore it is
        important to dispose of the original object when calling this method.
        e.i. when you need to reference the label of the block later.
        """
        assert isinstance(bb, IRBasicBlock), f"append_basic_block takes IRBasicBlock, got '{bb}'"
        last_bb = self.basic_blocks[-1] if len(self.basic_blocks) > 0 else None
        if last_bb and len(last_bb.instructions) == 0:
            # last basic block is empty, replace it
            old_label = self.basic_blocks[-1].label
            bb.label = old_label
            self.basic_blocks[-1] = bb
        else:
            self.basic_blocks.append(bb)

        return self.basic_blocks[-1]

    def get_basic_block(self, label: Optional[str] = None) -> IRBasicBlock:
        """
        Get basic block by label.
        If label is None, return the last basic block.
        """
        if label is None:
            return self.basic_blocks[-1]
        for bb in self.basic_blocks:
            if bb.label == label:
                return bb
        assert False, f"Basic block '{label}' not found"

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

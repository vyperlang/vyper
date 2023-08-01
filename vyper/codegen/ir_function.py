from typing import Optional
from vyper.codegen.ir_basicblock import IRBasicBlock, IRVariable, IRLabel


class IRFunctionBase:
    """
    Base class for IRFunction and IRFunctionIntrinsic
    """

    name: IRLabel  # symbol name
    args: list

    def __init__(self, name: IRLabel, args: list = []) -> None:
        self.name = name
        self.args = args


class IRFunction(IRFunctionBase):
    """
    Function that contains basic blocks.
    """

    basic_blocks: list["IRBasicBlock"]
    last_label: int
    last_variable: int

    def __init__(self, name: IRLabel) -> None:
        super().__init__(name)
        self.basic_blocks = []
        self.last_label = 0
        self.last_variable = 0

        self.append_basic_block(IRBasicBlock(name, self))

    def append_basic_block(self, bb: IRBasicBlock) -> IRBasicBlock:
        """
        Append basic block to function.
        """
        assert isinstance(bb, IRBasicBlock), f"append_basic_block takes IRBasicBlock, got '{bb}'"
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
            if bb.label.value == label:
                return bb
        raise AssertionError(f"Basic block '{label}' not found")

    def get_basic_block_after(self, label: IRLabel) -> IRBasicBlock:
        """
        Get basic block after label.
        """
        for i, bb in enumerate(self.basic_blocks[:-1]):
            if bb.label.value == label.value:
                return self.basic_blocks[i + 1]
        raise AssertionError(f"Basic block after '{label}' not found")

    def get_basicblocks_in(self, basic_block: IRBasicBlock) -> list[IRBasicBlock]:
        """
        Get basic blocks that contain label.
        """
        return [bb for bb in self.basic_blocks if basic_block.label in bb.in_set]

    def get_terminal_basicblocks(self) -> list[IRBasicBlock]:
        """
        Get basic blocks that contain label.
        """
        return [bb for bb in self.basic_blocks if bb.is_terminal()]

    def get_next_label(self) -> str:
        self.last_label += 1
        return IRLabel(f"{self.last_label}")

    def get_next_variable(self) -> str:
        self.last_variable += 1
        return IRVariable(f"%{self.last_variable}")

    def get_last_variable(self) -> str:
        return f"%{self.last_variable}"

    def remove_unreachable_blocks(self) -> int:
        removed = 0
        new_basic_blocks = []
        for bb in self.basic_blocks:
            if not bb.is_reachable and bb.label.value != "global":
                for bb2 in bb.out_set:
                    bb2.in_set.remove(bb)
                removed += 1
            else:
                new_basic_blocks.append(bb)
        self.basic_blocks = new_basic_blocks
        return removed

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

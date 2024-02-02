from typing import Optional

from vyper.venom.basicblock import (
    IRBasicBlock,
    IRInstruction,
    IRLabel,
    IROperand,
    IRVariable,
    MemType,
)

GLOBAL_LABEL = IRLabel("__global")


class IRFunction:
    """
    Function that contains basic blocks.
    """

    name: IRLabel  # symbol name
    entry_points: list[IRLabel]  # entry points
    args: list
    ctor_mem_size: Optional[int]
    immutables_len: Optional[int]
    basic_blocks: list[IRBasicBlock]
    data_segment: list[IRInstruction]
    last_label: int
    last_variable: int

    def __init__(self, name: IRLabel = None) -> None:
        if name is None:
            name = GLOBAL_LABEL
        self.name = name
        self.entry_points = []
        self.args = []
        self.ctor_mem_size = None
        self.immutables_len = None
        self.basic_blocks = []
        self.data_segment = []
        self.last_label = 0
        self.last_variable = 0

        self.add_entry_point(name)
        self.append_basic_block(IRBasicBlock(name, self))

    def add_entry_point(self, label: IRLabel) -> None:
        """
        Add entry point.
        """
        self.entry_points.append(label)

    def remove_entry_point(self, label: IRLabel) -> None:
        """
        Remove entry point.
        """
        self.entry_points.remove(label)

    def append_basic_block(self, bb: IRBasicBlock) -> IRBasicBlock:
        """
        Append basic block to function.
        """
        assert isinstance(bb, IRBasicBlock), f"append_basic_block takes IRBasicBlock, got '{bb}'"
        self.basic_blocks.append(bb)

        # TODO add sanity check somewhere that basic blocks have unique labels

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
        return [bb for bb in self.basic_blocks if basic_block.label in bb.cfg_in]

    def get_next_label(self) -> IRLabel:
        self.last_label += 1
        return IRLabel(f"{self.last_label}")

    def get_next_variable(
        self, mem_type: MemType = MemType.OPERAND_STACK, mem_addr: Optional[int] = None
    ) -> IRVariable:
        self.last_variable += 1
        return IRVariable(f"%{self.last_variable}", mem_type, mem_addr)

    def get_last_variable(self) -> str:
        return f"%{self.last_variable}"

    def remove_unreachable_blocks(self) -> int:
        removed = 0
        new_basic_blocks = []
        for bb in self.basic_blocks:
            if not bb.is_reachable and bb.label not in self.entry_points:
                removed += 1
            else:
                new_basic_blocks.append(bb)
        self.basic_blocks = new_basic_blocks
        return removed

    def append_data(self, opcode: str, args: list[IROperand]) -> None:
        """
        Append data
        """
        self.data_segment.append(IRInstruction(opcode, args))  # type: ignore

    @property
    def normalized(self) -> bool:
        """
        Check if function is normalized. A function is normalized if in the
        CFG, no basic block simultaneously has multiple inputs and outputs.
        That is, a basic block can be jumped to *from* multiple blocks, or it
        can jump *to* multiple blocks, but it cannot simultaneously do both.
        Having a normalized CFG makes calculation of stack layout easier when
        emitting assembly.
        """
        for bb in self.basic_blocks:
            # Ignore if there are no multiple predecessors
            if len(bb.cfg_in) <= 1:
                continue

            # Check if there is a branching jump at the end
            # of one of the predecessors
            for in_bb in bb.cfg_in:
                if len(in_bb.cfg_out) > 1:
                    return False

        # The function is normalized
        return True

    def copy(self):
        new = IRFunction(self.name)
        new.basic_blocks = self.basic_blocks.copy()
        new.data_segment = self.data_segment.copy()
        new.last_label = self.last_label
        new.last_variable = self.last_variable
        return new

    def __repr__(self) -> str:
        str = f"IRFunction: {self.name}\n"
        for bb in self.basic_blocks:
            str += f"{bb}\n"
        if len(self.data_segment) > 0:
            str += "Data segment:\n"
            for inst in self.data_segment:
                str += f"{inst}\n"
        return str.strip()

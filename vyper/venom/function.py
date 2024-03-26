from typing import Iterator, Optional

from vyper.codegen.ir_node import IRnode
from vyper.utils import OrderedSet
from vyper.venom.basicblock import (
    CFG_ALTERING_INSTRUCTIONS,
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

    # Used during code generation
    _ast_source_stack: list[int]
    _error_msg_stack: list[str]
    _bb_index: dict[str, int]

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

        self._ast_source_stack = []
        self._error_msg_stack = []
        self._bb_index = {}

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

        return self.basic_blocks[-1]

    def _get_basicblock_index(self, label: str):
        # perf: keep an "index" of labels to block indices to
        # perform fast lookup.
        # TODO: maybe better just to throw basic blocks in an ordered
        # dict of some kind.
        ix = self._bb_index.get(label, -1)
        if 0 <= ix < len(self.basic_blocks) and self.basic_blocks[ix].label == label:
            return ix
        # do a reindex
        self._bb_index = dict((bb.label.name, ix) for ix, bb in enumerate(self.basic_blocks))
        # sanity check - no duplicate labels
        assert len(self._bb_index) == len(self.basic_blocks)
        return self._bb_index[label]

    def get_basic_block(self, label: Optional[str] = None) -> IRBasicBlock:
        """
        Get basic block by label.
        If label is None, return the last basic block.
        """
        if label is None:
            return self.basic_blocks[-1]
        ix = self._get_basicblock_index(label)
        return self.basic_blocks[ix]

    def get_basic_block_after(self, label: IRLabel) -> IRBasicBlock:
        """
        Get basic block after label.
        """
        ix = self._get_basicblock_index(label.value)
        if 0 <= ix < len(self.basic_blocks) - 1:
            return self.basic_blocks[ix + 1]
        raise AssertionError(f"Basic block after '{label}' not found")

    def get_terminal_basicblocks(self) -> Iterator[IRBasicBlock]:
        """
        Get basic blocks that are terminal.
        """
        for bb in self.basic_blocks:
            if bb.is_terminal:
                yield bb

    def get_basicblocks_in(self, basic_block: IRBasicBlock) -> list[IRBasicBlock]:
        """
        Get basic blocks that point to the given basic block
        """
        return [bb for bb in self.basic_blocks if basic_block.label in bb.cfg_in]

    def get_next_label(self, suffix: str = "") -> IRLabel:
        if suffix != "":
            suffix = f"_{suffix}"
        self.last_label += 1
        return IRLabel(f"{self.last_label}{suffix}")

    def get_next_variable(
        self, mem_type: MemType = MemType.OPERAND_STACK, mem_addr: Optional[int] = None
    ) -> IRVariable:
        self.last_variable += 1
        return IRVariable(f"%{self.last_variable}", mem_type, mem_addr)

    def get_last_variable(self) -> str:
        return f"%{self.last_variable}"

    def remove_unreachable_blocks(self) -> int:
        self._compute_reachability()

        removed = []
        new_basic_blocks = []

        # Remove unreachable basic blocks
        for bb in self.basic_blocks:
            if not bb.is_reachable:
                removed.append(bb)
            else:
                new_basic_blocks.append(bb)
        self.basic_blocks = new_basic_blocks

        # Remove phi instructions that reference removed basic blocks
        for bb in removed:
            for out_bb in bb.cfg_out:
                out_bb.remove_cfg_in(bb)
                for inst in out_bb.instructions:
                    if inst.opcode != "phi":
                        continue
                    in_labels = inst.get_label_operands()
                    if bb.label in in_labels:
                        out_bb.remove_instruction(inst)

        return len(removed)

    def _compute_reachability(self) -> None:
        """
        Compute reachability of basic blocks.
        """
        for bb in self.basic_blocks:
            bb.reachable = OrderedSet()
            bb.is_reachable = False

        for entry in self.entry_points:
            entry_bb = self.get_basic_block(entry.value)
            self._compute_reachability_from(entry_bb)

    def _compute_reachability_from(self, bb: IRBasicBlock) -> None:
        """
        Compute reachability of basic blocks from bb.
        """
        if bb.is_reachable:
            return
        bb.is_reachable = True
        for inst in bb.instructions:
            if inst.opcode in CFG_ALTERING_INSTRUCTIONS or inst.opcode == "invoke":
                for op in inst.get_label_operands():
                    out_bb = self.get_basic_block(op.value)
                    bb.reachable.add(out_bb)
                    self._compute_reachability_from(out_bb)

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

    def push_source(self, ir):
        if isinstance(ir, IRnode):
            self._ast_source_stack.append(ir.ast_source)
            self._error_msg_stack.append(ir.error_msg)

    def pop_source(self):
        assert len(self._ast_source_stack) > 0, "Empty source stack"
        self._ast_source_stack.pop()
        assert len(self._error_msg_stack) > 0, "Empty error stack"
        self._error_msg_stack.pop()

    @property
    def ast_source(self) -> Optional[int]:
        return self._ast_source_stack[-1] if len(self._ast_source_stack) > 0 else None

    @property
    def error_msg(self) -> Optional[str]:
        return self._error_msg_stack[-1] if len(self._error_msg_stack) > 0 else None

    def copy(self):
        new = IRFunction(self.name)
        new.basic_blocks = self.basic_blocks.copy()
        new.data_segment = self.data_segment.copy()
        new.last_label = self.last_label
        new.last_variable = self.last_variable
        return new

    def as_graph(self) -> str:
        import html

        def _make_label(bb):
            ret = '<<table border="1" cellborder="0" cellspacing="0">'
            ret += f'<tr><td align="left"><b>{html.escape(str(bb.label))}</b></td></tr>\n'
            for inst in bb.instructions:
                ret += f'<tr ><td align="left">{html.escape(str(inst))}</td></tr>\n'
            ret += "</table>>"

            return ret
            # return f"{bb.label.value}:\n" + "\n".join([f"    {inst}" for inst in bb.instructions])

        ret = "digraph G {\n"

        for bb in self.basic_blocks:
            for out_bb in bb.cfg_out:
                ret += f'    "{bb.label.value}" -> "{out_bb.label.value}"\n'

        for bb in self.basic_blocks:
            ret += f'    "{bb.label.value}" [shape=plaintext, '
            ret += f'label={_make_label(bb)}, fontname="Courier" fontsize="8"]\n'

        ret += "}\n"
        return ret

    def __repr__(self) -> str:
        str = f"IRFunction: {self.name}\n"
        for bb in self.basic_blocks:
            str += f"{bb}\n"
        if len(self.data_segment) > 0:
            str += "Data segment:\n"
            for inst in self.data_segment:
                str += f"{inst}\n"
        return str.strip()

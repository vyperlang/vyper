from __future__ import annotations

import textwrap
from typing import TYPE_CHECKING, Iterator, Optional

from vyper.codegen.ir_node import IRnode
from vyper.venom.basicblock import IRBasicBlock, IRLabel, IRVariable

if TYPE_CHECKING:
    from vyper.venom.context import IRContext


class IRFunction:
    """
    Function that contains basic blocks.
    """

    name: IRLabel  # symbol name
    ctx: IRContext
    last_variable: int
    _basic_block_dict: dict[str, IRBasicBlock]

    # Internal-call metadata (excluding return_pc):
    # - number of invoke params
    # - whether first invoke param is a memory return buffer
    _invoke_param_count: Optional[int]
    _has_memory_return_buffer_param: Optional[bool]

    # Used during code generation
    _ast_source_stack: list[IRnode]
    _error_msg_stack: list[Optional[str]]

    def __init__(self, name: IRLabel, ctx: IRContext = None):
        self.ctx = ctx  # type: ignore
        self.name = name
        self._basic_block_dict = {}

        self.last_variable = 0

        self._invoke_param_count = None
        self._has_memory_return_buffer_param = None

        self._ast_source_stack = []
        self._error_msg_stack = []

        self.append_basic_block(IRBasicBlock(name, self))

    @property
    def entry(self) -> IRBasicBlock:
        return next(self.get_basic_blocks())

    def append_basic_block(self, bb: IRBasicBlock):
        """
        Append basic block to function.
        """
        assert isinstance(bb, IRBasicBlock), bb
        assert bb.label.name not in self._basic_block_dict, bb.label
        self._basic_block_dict[bb.label.name] = bb

    def remove_basic_block(self, bb: IRBasicBlock):
        assert isinstance(bb, IRBasicBlock), bb
        del self._basic_block_dict[bb.label.name]

    def has_basic_block(self, label: str) -> bool:
        return label in self._basic_block_dict

    def get_basic_block(self, label: Optional[str] = None) -> IRBasicBlock:
        """
        Get basic block by label.
        If label is None, return the last basic block.
        """
        if label is None:
            return next(reversed(self._basic_block_dict.values()))

        return self._basic_block_dict[label]

    def clear_basic_blocks(self):
        self._basic_block_dict.clear()

    def get_basic_blocks(self) -> Iterator[IRBasicBlock]:
        """
        Get an iterator over this function's basic blocks
        """
        return iter(self._basic_block_dict.values())

    @property
    def num_basic_blocks(self) -> int:
        return len(self._basic_block_dict)

    @property
    def code_size_cost(self) -> int:
        return sum(bb.code_size_cost for bb in self.get_basic_blocks())

    def get_next_variable(self) -> IRVariable:
        self.last_variable += 1
        return IRVariable(f"%{self.last_variable}")

    def get_last_variable(self) -> str:
        return f"%{self.last_variable}"

    def push_source(self, ir):
        if isinstance(ir, IRnode):
            self._ast_source_stack.append(ir.ast_source)
            self._error_msg_stack.append(ir.error_msg)

    def push_error_msg(self, error_msg: Optional[str]):
        """Push an error message without changing ast_source."""
        self._error_msg_stack.append(error_msg)

    def pop_error_msg(self):
        """Pop an error message."""
        assert len(self._error_msg_stack) > 0, "Empty error stack"
        self._error_msg_stack.pop()

    def pop_source(self):
        assert len(self._ast_source_stack) > 0, "Empty source stack"
        self._ast_source_stack.pop()
        assert len(self._error_msg_stack) > 0, "Empty error stack"
        self._error_msg_stack.pop()

    @property
    def ast_source(self) -> Optional[IRnode]:
        return self._ast_source_stack[-1] if len(self._ast_source_stack) > 0 else None

    @property
    def error_msg(self) -> Optional[str]:
        return self._error_msg_stack[-1] if len(self._error_msg_stack) > 0 else None

    def copy(self):
        new = IRFunction(self.name)
        for bb in self.get_basic_blocks():
            new_bb = bb.copy()
            new.append_basic_block(new_bb)

        return new

    def as_graph(self, only_subgraph=False) -> str:
        """
        Return the function as a graphviz dot string. If only_subgraph is True, only return the
        subgraph, not the full digraph -for embedding in a larger graph-
        """
        import html

        def _make_label(bb):
            ret = '<<table border="1" cellborder="0" cellspacing="0">'
            ret += f'<tr><td align="left"><b>{html.escape(str(bb.label))}</b></td></tr>\n'
            for inst in bb.instructions:
                ret += f'<tr ><td align="left">{html.escape(str(inst))}</td></tr>\n'
            ret += "</table>>"

            return ret
            # return f"{bb.label.value}:\n" + "\n".join([f"    {inst}" for inst in bb.instructions])

        ret = []

        if not only_subgraph:
            ret.append("digraph G {{")
        ret.append(f"subgraph {repr(self.name)} {{")

        for bb in self.get_basic_blocks():
            for out_bb in bb.out_bbs:
                ret.append(f'    "{bb.label.value}" -> "{out_bb.label.value}"')

        for bb in self.get_basic_blocks():
            ret.append(f'    "{bb.label.value}" [shape=plaintext, ')
            ret.append(f'label={_make_label(bb)}, fontname="Courier" fontsize="8"]')

        ret.append("}\n")
        if not only_subgraph:
            ret.append("}\n")

        return "\n".join(ret)

    def __repr__(self) -> str:
        ret = f"function {self.name} {{\n"
        for bb in self.get_basic_blocks():
            bb_str = textwrap.indent(str(bb), "  ")
            ret += f"{bb_str}\n"
        ret = ret.strip() + "\n}"
        ret += f"  ; close function {self.name}"
        return ret

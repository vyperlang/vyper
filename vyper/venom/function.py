from __future__ import annotations

import textwrap
from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterator, Optional

from vyper.codegen.ir_node import IRnode
from vyper.venom.basicblock import IRBasicBlock, IRLabel, IRVariable

if TYPE_CHECKING:
    from vyper.venom.context import IRContext


@dataclass(frozen=True)
class FmpSignature:
    """
    Frozen FMP calling-convention shape of a function.

    Written by FmpLoweringPass when it materializes the convention,
    resealed by FmpPrunePass if the hidden FMP param is deleted, and
    reconstructed by the parser from the function-header annotation
    (`[fmp_lowered]` / `[fmp_lowered, fmp_publishes]`) plus the
    `fmp_param` opcode. Once set, it is authoritative: callers augment
    invokes against it and the post-lowering checks compare the physical
    shape against it.
    """

    has_fmp_param: bool
    publishes: bool

    @property
    def attrs(self) -> list[str]:
        # the function-header annotation attributes in the Venom text format.
        # `has_fmp_param` is not part of the annotation: it is carried
        # syntactically by the `fmp_param` opcode.
        attrs = ["fmp_lowered"]
        if self.publishes:
            attrs.append("fmp_publishes")
        return attrs


class IRFunction:
    """
    Function that contains basic blocks.
    """

    name: IRLabel  # symbol name
    ctx: IRContext
    last_variable: int
    _basic_block_dict: dict[str, IRBasicBlock]

    # Internal-call metadata (excluding return_pc):
    # - whether first invoke param is a memory return buffer
    # - number of user-visible return values produced by invoke
    # The user-arg count itself is syntactic: plain `param` instructions
    # are exactly the user params (`fmp_param`/`retpc_param` name the
    # hidden slots).
    _has_memory_return_buffer_param: Optional[bool]
    _return_value_count: Optional[int]

    # Frozen FMP convention shape; None until FmpLoweringPass runs.
    _fmp_signature: Optional[FmpSignature]

    # Opt-out flag for FunctionInlinerPass; set via the `[noinline]`
    # function-header annotation.
    noinline: bool

    # Used during code generation
    _ast_source_stack: list[IRnode]
    _error_msg_stack: list[Optional[str]]

    def __init__(self, name: IRLabel, ctx: IRContext = None):
        self.ctx = ctx  # type: ignore
        self.name = name
        self._basic_block_dict = {}

        self.last_variable = 0

        self._has_memory_return_buffer_param = None
        self._return_value_count = None
        self._fmp_signature = None
        self.noinline = False

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
        new._has_memory_return_buffer_param = self._has_memory_return_buffer_param
        new._return_value_count = self._return_value_count
        new._fmp_signature = self._fmp_signature
        new.noinline = self.noinline
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
        attrs = []
        if self._fmp_signature is not None:
            attrs.extend(self._fmp_signature.attrs)
        if self.noinline:
            attrs.append("noinline")
        annotation = ""
        if len(attrs) > 0:
            annotation = f" [{', '.join(attrs)}]"
        ret = f"function {self.name}{annotation} {{\n"
        for bb in self.get_basic_blocks():
            bb_str = textwrap.indent(str(bb), "  ")
            ret += f"{bb_str}\n"
        ret = ret.strip() + "\n}"
        ret += f"  ; close function {self.name}"
        return ret

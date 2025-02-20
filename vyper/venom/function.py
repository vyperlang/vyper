import textwrap
from dataclasses import dataclass
from typing import Iterator, Optional

from vyper.codegen.ir_node import IRnode
from vyper.venom.basicblock import IRBasicBlock, IRLabel, IRVariable


@dataclass
class IRParameter:
    name: str
    index: int
    offset: int
    size: int
    call_site_var: Optional[IRVariable]
    func_var: Optional[IRVariable]
    addr_var: Optional[IRVariable]


class IRFunction:
    """
    Function that contains basic blocks.
    """

    name: IRLabel  # symbol name
    ctx: "IRContext"  # type: ignore # noqa: F821
    args: list
    last_variable: int
    _basic_block_dict: dict[str, IRBasicBlock]

    # Used during code generation
    _ast_source_stack: list[IRnode]
    _error_msg_stack: list[str]

    def __init__(self, name: IRLabel, ctx: "IRContext" = None) -> None:  # type: ignore # noqa: F821
        self.ctx = ctx
        self.name = name
        self.args = []
        self._basic_block_dict = {}

        self.last_variable = 0

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

    def get_terminal_basicblocks(self) -> Iterator[IRBasicBlock]:
        """
        Get basic blocks that are terminal.
        """
        for bb in self.get_basic_blocks():
            if bb.is_terminal:
                yield bb

    def get_next_variable(self) -> IRVariable:
        self.last_variable += 1
        return IRVariable(f"%{self.last_variable}")

    def get_last_variable(self) -> str:
        return f"%{self.last_variable}"

    def remove_unreachable_blocks(self) -> int:
        # Remove unreachable basic blocks
        # pre: requires CFG analysis!
        # NOTE: should this be a pass?

        removed = set()

        for bb in self.get_basic_blocks():
            if not bb.is_reachable:
                removed.add(bb)

        for bb in removed:
            self.remove_basic_block(bb)

        # Remove phi instructions that reference removed basic blocks
        for bb in self.get_basic_blocks():
            for in_bb in list(bb.cfg_in):
                if in_bb not in removed:
                    continue

                bb.remove_cfg_in(in_bb)

            # TODO: only run this if cfg_in changed
            bb.fix_phi_instructions()

        return len(removed)

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
        for bb in self.get_basic_blocks():
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

    def get_param_at_offset(self, offset: int) -> Optional[IRParameter]:
        for param in self.args:
            if param.offset == offset:
                return param
        return None

    def get_param_by_name(self, var: IRVariable | str) -> Optional[IRParameter]:
        if isinstance(var, str):
            var = IRVariable(var)
        for param in self.args:
            if f"%{param.name}" == var.name:
                return param
        return None

    @property
    def ast_source(self) -> Optional[IRnode]:
        return self._ast_source_stack[-1] if len(self._ast_source_stack) > 0 else None

    @property
    def error_msg(self) -> Optional[str]:
        return self._error_msg_stack[-1] if len(self._error_msg_stack) > 0 else None

    def chain_basic_blocks(self) -> None:
        """
        Chain basic blocks together. If a basic block is not terminated, jump to the next one.
        Otherwise, append a stop instruction. This is necessary for the IR to be valid, and is
        done after the IR is generated.
        """
        bbs = list(self.get_basic_blocks())
        for i, bb in enumerate(bbs):
            if bb.is_terminated:
                continue

            if i < len(bbs) - 1:
                # TODO: revisit this. When contructor calls internal functions
                # they are linked to the last ctor block. Should separate them
                # before this so we don't have to handle this here
                if bbs[i + 1].label.value.startswith("internal"):
                    bb.append_instruction("stop")
                else:
                    bb.append_instruction("jmp", bbs[i + 1].label)
            else:
                bb.append_instruction("stop")

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
        ret.append(f'subgraph "{self.name}" {{')

        for bb in self.get_basic_blocks():
            for out_bb in bb.cfg_out:
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

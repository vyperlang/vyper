import json
from typing import Optional

from lark import Lark, Transformer

from vyper.venom.basicblock import (
    IRBasicBlock,
    IRInstruction,
    IRLabel,
    IRLiteral,
    IROperand,
    IRVariable,
)
from vyper.venom.context import DataItem, DataSection, IRContext
from vyper.venom.function import IRFunction

VENOM_GRAMMAR = """
    %import common.DIGIT
    %import common.HEXDIGIT
    %import common.LETTER
    %import common.WS
    %import common.INT
    %import common.SIGNED_INT
    %import common.ESCAPED_STRING
    %import common.NEWLINE

    # Allow multiple comment styles
    COMMENT: ";" /[^\\n]*/ | "//" /[^\\n]*/ | "#" /[^\\n]*/

    start: function* data_segment?

    # Function contains lines, each line is terminated by NEWLINE or EOF
    function: "function" func_name "{" line* "}"

    # A line can contain a label declaration, a statement, or be empty
    line: label_decl NEWLINE* | statement NEWLINE* | NEWLINE

    # Label declaration is IDENT or ESCAPED_STRING followed by ":"
    label_decl: (IDENT | ESCAPED_STRING) ":"

    # Statements are either assignments or instructions
    statement: assignment | instruction
    assignment: VAR_IDENT "=" expr
    expr: instruction | operand

    # Instructions are IDENT followed by optional operands
    instruction: IDENT operands_list?

    operands_list: operand ("," operand)*

    operand: VAR_IDENT | CONST | label_ref

    CONST: SIGNED_INT | "0x" HEXDIGIT+
    VAR_IDENT: "%" (DIGIT|LETTER|"_"|":")+

    # Non-terminal rules for different contexts
    func_name: IDENT | ESCAPED_STRING
    label_name: IDENT | ESCAPED_STRING
    label_ref: "@" (IDENT | ESCAPED_STRING)

    # Data segment rules remain the same
    data_segment: "data" "readonly" "{" data_section* "}"
    data_section: "dbsection" label_name ":" data_item+
    data_item: "db" (HEXSTR | label_ref) NEWLINE*

    DOUBLE_QUOTE: "\\""
    IDENT: (DIGIT|LETTER|"_")+
    HEXSTR: "x" DOUBLE_QUOTE (HEXDIGIT|"_")+ DOUBLE_QUOTE

    %ignore WS
    %ignore COMMENT
    """

# Use LALR parser without contextual lexer since grammar is now unambiguous
VENOM_PARSER = Lark(VENOM_GRAMMAR, parser="lalr")


def _set_last_var(function: IRFunction) -> None:
    for bb in function.get_basic_blocks():
        for inst in bb.instructions:
            if inst.output is None:
                continue
            value = inst.output.value
            assert value.startswith("%")
            varname = value[1:]
            if varname.isdigit():
                function.last_variable = max(function.last_variable, int(varname))


def _set_last_label(ctx: IRContext) -> None:
    for function in ctx.functions.values():
        for bb in function.get_basic_blocks():
            label = bb.label.value
            label_head, *_ = label.split("_", maxsplit=1)
            if label_head.isdigit():
                ctx.last_label = max(int(label_head), ctx.last_label)


def _unescape(s: str) -> str:
    """
    Unescape the escaped string. This is the inverse of `IRLabel.__repr__()`.
    """
    if s.startswith('"'):
        return json.loads(s)
    return s


class _TypedItem:
    """Base class for typed items in the parse tree."""

    def __init__(self, children: list) -> None:
        self.children = children


class _DataSegment(_TypedItem):
    """Represents a data segment in the parse tree."""

    pass


class _LabelDecl:
    """Represents a label declaration in the parse tree."""

    def __init__(self, label: str) -> None:
        self.label = label


class VenomTransformer(Transformer):
    def start(self, children) -> IRContext:
        ctx = IRContext()
        if len(children) > 0 and isinstance(children[-1], _DataSegment):
            ctx.data_segment = children.pop().children

        funcs = children
        for fn_name, lines in funcs:
            fn = ctx.create_function(fn_name)
            if ctx.entry_function is None:
                ctx.entry_function = fn
            fn._basic_block_dict.clear()

            # Process lines to reconstruct blocks
            current_block_label: Optional[str] = None
            current_block_instructions: list[IRInstruction] = []
            blocks: list[tuple[str, list[IRInstruction]]] = []

            for item in lines:
                if isinstance(item, _LabelDecl):
                    # Save previous block if exists
                    if current_block_label is not None:
                        blocks.append((current_block_label, current_block_instructions))
                    # Start new block
                    current_block_label = item.label
                    current_block_instructions = []
                elif isinstance(item, IRInstruction):
                    # Add instruction to current block
                    if current_block_label is None:
                        raise ValueError("Instruction found before any label declaration")
                    current_block_instructions.append(item)

            # Save last block
            if current_block_label is not None:
                blocks.append((current_block_label, current_block_instructions))

            # Create basic blocks
            for block_name, instructions in blocks:
                bb = IRBasicBlock(IRLabel(block_name, True), fn)
                fn.append_basic_block(bb)

                for instruction in instructions:
                    assert isinstance(instruction, IRInstruction)  # help mypy
                    bb.insert_instruction(instruction)

            _set_last_var(fn)
        _set_last_label(ctx)

        return ctx

    def function(self, children) -> tuple[str, list]:
        name = children[0]
        lines = []
        # Filter out None values from empty lines
        for child in children[1:]:
            if child is not None:
                lines.append(child)
        return name, lines

    def line(self, children) -> Optional[_LabelDecl | IRInstruction]:
        # A line might have just a NEWLINE (empty line) which we skip
        if len(children) == 0 or (len(children) == 1 and children[0].type == "NEWLINE"):
            return None
        # Otherwise return the label_decl or statement
        return children[0]

    def label_decl(self, children) -> _LabelDecl:
        label = _unescape(str(children[0]))
        return _LabelDecl(label)

    def statement(self, children) -> IRInstruction:
        return children[0]

    def data_segment(self, children) -> _DataSegment:
        return _DataSegment(children)

    def data_section(self, children) -> DataSection:
        label = IRLabel(children[0], True)
        data_items = children[1:]
        assert all(isinstance(item, DataItem) for item in data_items)
        return DataSection(label, data_items)

    def data_item(self, children) -> DataItem:
        item = children[0]
        if isinstance(item, IRLabel):
            return DataItem(item)
        # Handle HEXSTR
        assert isinstance(item, str)
        assert item.startswith('x"')
        assert item.endswith('"')
        item = item.removeprefix('x"').removesuffix('"')
        item = item.replace("_", "")
        return DataItem(bytes.fromhex(item))

    def assignment(self, children) -> IRInstruction:
        to, value = children
        if isinstance(value, IRInstruction):
            value.output = to
            return value
        if isinstance(value, (IRLiteral, IRVariable, IRLabel)):
            return IRInstruction("store", [value], output=to)
        raise TypeError(f"Unexpected value {value} of type {type(value)}")

    def expr(self, children) -> IRInstruction | IROperand:
        return children[0]

    def instruction(self, children) -> IRInstruction:
        if len(children) == 1:
            # Just the opcode (IDENT)
            opcode = str(children[0])
            operands = []
        else:
            assert len(children) == 2
            # IDENT and operands_list
            opcode = str(children[0])
            operands = children[1]

        # reverse operands, venom internally represents top of stack
        # as rightmost operand
        if opcode == "invoke":
            # reverse stack arguments but not label arg
            # invoke <target> <stack arguments>
            operands = [operands[0]] + list(reversed(operands[1:]))
        # special cases: operands with labels look better un-reversed
        elif opcode not in ("jmp", "jnz", "djmp", "phi"):
            operands.reverse()
        return IRInstruction(opcode, operands)

    def operands_list(self, children) -> list[IROperand]:
        return children

    def operand(self, children) -> IROperand:
        return children[0]

    def func_name(self, children) -> str:
        # func_name can be IDENT or ESCAPED_STRING
        return _unescape(str(children[0]))

    def label_name(self, children) -> str:
        # label_name can be IDENT or ESCAPED_STRING
        return _unescape(str(children[0]))

    def label_ref(self, children) -> IRLabel:
        # label_ref is "@" followed by IDENT or ESCAPED_STRING
        label = _unescape(str(children[0]))
        if label.startswith("@"):
            label = label[1:]
        return IRLabel(label, True)

    def VAR_IDENT(self, var_ident) -> IRVariable:
        return IRVariable(var_ident[1:])

    def CONST(self, val) -> IRLiteral:
        if str(val).startswith("0x"):
            return IRLiteral(int(val, 16))
        return IRLiteral(int(val))

    def IDENT(self, val) -> str:
        return val.value

    def HEXSTR(self, val) -> str:
        return val.value


def parse_venom(source: str) -> IRContext:
    tree = VENOM_PARSER.parse(source)
    ctx = VenomTransformer().transform(tree)
    assert isinstance(ctx, IRContext)  # help mypy
    return ctx

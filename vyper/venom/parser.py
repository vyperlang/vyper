import json
from typing import Optional

from lark import Lark, Transformer

from vyper.venom.basicblock import (
    IRBasicBlock,
    IRHexString,
    IRInstruction,
    IRLabel,
    IRLiteral,
    IROperand,
    IRVariable,
)
from vyper.venom.context import IRContext
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

    start: (global_label | function)*

    # Global label definitions with optional address override
    global_label: label_name ":" CONST

    function: "function" func_name "{" block_content "}"

    block_content: (label_decl | statement)*

    label_decl: (IDENT | ESCAPED_STRING) ":" ("@" CONST)? ("[" tag_list "]")? NEWLINE+

    tag_list: tag ("," tag)*
    tag: IDENT

    statement: (assignment | instruction) NEWLINE+
    assignment: VAR_IDENT "=" expr
    expr: instruction | operand

    instruction: IDENT operands_list?
               | DB operands_list

    operands_list: operand ("," operand)*

    operand: VAR_IDENT | CONST | label_ref | HEXSTR

    VAR_IDENT: "%" (DIGIT|LETTER|"_"|":")+

    # non-terminal rules for different contexts
    func_name: IDENT | ESCAPED_STRING
    label_name: IDENT | ESCAPED_STRING
    label_ref: "@" (IDENT | ESCAPED_STRING)

    DOUBLE_QUOTE: "\\""
    IDENT: (DIGIT|LETTER|"_")+
    DB: "db"
    HEXSTR: "x" DOUBLE_QUOTE (HEXDIGIT|"_")+ DOUBLE_QUOTE
    CONST: SIGNED_INT | "0x" HEXDIGIT+

    %ignore WS
    %ignore COMMENT
    """

VENOM_PARSER = Lark(VENOM_GRAMMAR, parser="lalr")


def _set_last_var(fn: IRFunction):
    for bb in fn.get_basic_blocks():
        for inst in bb.instructions:
            if inst.output is None:
                continue
            value = inst.output.value
            assert value.startswith("%")
            varname = value[1:]
            if varname.isdigit():
                fn.last_variable = max(fn.last_variable, int(varname))


def _set_last_label(ctx: IRContext):
    for fn in ctx.functions.values():
        for bb in fn.get_basic_blocks():
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
    def __init__(self, children: list) -> None:
        self.children = children


class _GlobalLabel(_TypedItem):
    pass


class _LabelDecl:
    """Represents a block declaration in the parse tree."""

    def __init__(
        self, label: str, address: Optional[int] = None, tags: Optional[list[str]] = None
    ) -> None:
        self.label = label
        self.address = address
        self.tags = tags or []


class VenomTransformer(Transformer):
    def start(self, children) -> IRContext:
        ctx = IRContext()

        # Separate global labels and functions
        global_labels = []
        funcs = []

        for child in children:
            if isinstance(child, _GlobalLabel):
                global_labels.append(child)
            else:
                funcs.append(child)

        # Process global labels
        for global_label in global_labels:
            name, address = global_label.children
            ctx.add_global_label(name, address)

        # Process functions
        for fn_name, items in funcs:
            fn = ctx.create_function(fn_name)
            if ctx.entry_function is None:
                ctx.entry_function = fn
            fn.clear_basic_blocks()

            # reconstruct blocks from flat list of labels and instructions.
            # the grammar parses labels and statements as a flat sequence,
            # so we need to group instructions by their preceding label.
            # this makes the grammar compatible with LALR(1).
            # blocks are implicitly defined by label declarations - each
            # label starts a new block that contains all instructions until
            # the next label or end of function.
            current_block_label: Optional[str] = None
            current_block_address: Optional[int] = None
            current_block_tags: list[str] = []
            current_block_instructions: list[IRInstruction] = []
            blocks: list[tuple[str, Optional[int], list[IRInstruction], list[str]]] = []

            for item in items:
                if isinstance(item, _LabelDecl):
                    if current_block_label is not None:
                        blocks.append(
                            (
                                current_block_label,
                                current_block_address,
                                current_block_instructions,
                                current_block_tags,
                            )
                        )
                    current_block_label = item.label
                    current_block_address = item.address
                    current_block_tags = item.tags
                    current_block_instructions = []
                elif isinstance(item, IRInstruction):
                    if current_block_label is None:
                        raise ValueError("Instruction found before any label declaration")
                    current_block_instructions.append(item)

            if current_block_label is not None:
                blocks.append(
                    (
                        current_block_label,
                        current_block_address,
                        current_block_instructions,
                        current_block_tags,
                    )
                )

            for block_data in blocks:
                # All blocks now have: (block_name, address, instructions, tags)
                block_name, address, instructions, tags = block_data
                if address is not None:
                    bb = IRBasicBlock(IRLabel(block_name, True, address), fn)
                else:
                    bb = IRBasicBlock(IRLabel(block_name, True), fn)

                # Set is_volatile if "pinned" tag is present
                if "pinned" in tags:
                    bb.is_pinned = True

                fn.append_basic_block(bb)

                for instruction in instructions:
                    assert isinstance(instruction, IRInstruction)  # help mypy
                    bb.insert_instruction(instruction)

            _set_last_var(fn)

        _set_last_label(ctx)

        return ctx

    def global_label(self, children) -> _GlobalLabel:
        name, address_literal = children
        return _GlobalLabel([name, address_literal.value])

    def function(self, children) -> tuple[str, list]:
        name, block_content = children
        return name, block_content

    def block_content(self, children) -> list:
        # children contains label_decls and statements
        return children

    def label_decl(self, children) -> _LabelDecl:
        # children[0] is the label, optional address, optional tags, then NEWLINE tokens
        label = _unescape(str(children[0]))
        address = None
        tags = []

        # Process children after the label
        for child in children[1:]:
            if isinstance(child, IRLiteral):
                address = child.value
            elif isinstance(child, list):  # tag_list returns a list
                tags = child

        return _LabelDecl(label, address, tags)

    def statement(self, children) -> IRInstruction:
        # children[0] is the instruction/assignment, rest are NEWLINE tokens
        return children[0]

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
            # just the opcode (IDENT)
            opcode = str(children[0])
            # Handle Lark tokens
            if hasattr(children[0], "value"):
                opcode = children[0].value
            operands = []
        elif len(children) == 2:
            # Two cases: IDENT + operands_list OR "db" + operands_list
            opcode = str(children[0])
            # Handle Lark tokens
            if hasattr(children[0], "value"):
                opcode = children[0].value
            operands = children[1]
        else:
            raise ValueError(f"Unexpected instruction children: {children}")

        # reverse operands, venom internally represents top of stack
        # as rightmost operand
        if opcode == "invoke":
            # reverse stack arguments but not label arg
            # invoke <target> <stack arguments>
            operands = [operands[0]] + list(reversed(operands[1:]))
        # special cases: operands with labels look better un-reversed
        elif opcode not in ("jmp", "jnz", "djmp", "phi", "db"):
            operands.reverse()
        return IRInstruction(opcode, operands)

    def operands_list(self, children) -> list[IROperand]:
        return children

    def operand(self, children) -> IROperand:
        operand = children[0]
        if isinstance(operand, str) and operand.startswith('x"'):
            # Handle hex strings - convert to IRHexString
            assert operand.endswith('"')
            hex_content = operand.removeprefix('x"').removesuffix('"')
            hex_content = hex_content.replace("_", "")
            return IRHexString(bytes.fromhex(hex_content))
        return operand

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

    def DB(self, val) -> str:
        return val.value

    def HEXSTR(self, val) -> str:
        return val.value

    def tag_list(self, children) -> list[str]:
        return children

    def tag(self, children) -> str:
        return str(children[0])


def parse_venom(source: str) -> IRContext:
    tree = VENOM_PARSER.parse(source)
    ctx = VenomTransformer().transform(tree)
    assert isinstance(ctx, IRContext)  # help mypy
    return ctx

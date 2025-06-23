import json
from typing import Optional

from lark import Lark, Transformer

from vyper.venom import convert_data_segment_to_function
from vyper.venom.basicblock import (
    IRBasicBlock,
    IRInstruction,
    IRLabel,
    IRLiteral,
    IROperand,
    IRVariable,
    IRHexString,
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

    start: (global_label | function)* data_segment?

    # Global label definitions with optional address override
    global_label: label_name ":" CONST

    function: "function" func_name "{" block_content "}"

    block_content: (label_decl | statement)*

    label_decl: (IDENT | ESCAPED_STRING) ":" ("@" CONST)? NEWLINE+

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

    data_segment: "data" "readonly" "{" data_section* "}"
    data_section: label_name ":" NEWLINE+ data_item+
    data_item: DB (HEXSTR | label_ref) NEWLINE+

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


class _DataSegment(_TypedItem):
    pass


class _GlobalLabel(_TypedItem):
    pass
class _LabelDecl:
    """Represents a block declaration in the parse tree."""

    def __init__(self, label: str, address: Optional[int] = None) -> None:
        self.label = label
        self.address = address


class VenomTransformer(Transformer):
    def start(self, children) -> IRContext:
        ctx = IRContext()
        
        # Separate global labels, functions, and data segments
        global_labels = []
        funcs = []
        data_segment = None
        
        for child in children:
            if isinstance(child, _GlobalLabel):
                global_labels.append(child)
            elif isinstance(child, _DataSegment):
                data_segment = child
            else:
                funcs.append(child)
        
        # Process global labels
        for global_label in global_labels:
            name, address = global_label.children
            ctx.add_global_label(name, address)
        
        # Process functions first
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
            current_block_instructions: list[IRInstruction] = []
            blocks: list[tuple[str, Optional[int], list[IRInstruction]]] = []

            for item in items:
                if isinstance(item, _LabelDecl):
                    if current_block_label is not None:
                        blocks.append((current_block_label, current_block_address, current_block_instructions))
                    current_block_label = item.label
                    current_block_address = item.address
                    current_block_instructions = []
                elif isinstance(item, IRInstruction):
                    if current_block_label is None:
                        raise ValueError("Instruction found before any label declaration")
                    current_block_instructions.append(item)

            if current_block_label is not None:
                blocks.append((current_block_label, current_block_address, current_block_instructions))

            for block_data in blocks:
                # All blocks now have: (block_name, address, instructions)
                block_name, address, instructions = block_data
                if address is not None:
                    bb = IRBasicBlock(IRLabel(block_name, True, address), fn)
                else:
                    bb = IRBasicBlock(IRLabel(block_name, True), fn)
                
                fn.append_basic_block(bb)

                for instruction in instructions:
                    assert isinstance(instruction, IRInstruction)  # help mypy
                    bb.insert_instruction(instruction)

        # Process data segment after functions by converting it to a regular function
        if data_segment:
            self._add_revert_postamble_function(ctx)
            convert_data_segment_to_function(ctx, data_segment.children)

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
        # children[0] is the label, optional address, then NEWLINE tokens
        label = _unescape(str(children[0]))
        address = None
        if len(children) > 1 and isinstance(children[1], IRLiteral):
            address = children[1].value
        return _LabelDecl(label, address)

    def statement(self, children) -> IRInstruction:
        # children[0] is the instruction/assignment, rest are NEWLINE tokens
        return children[0]

    def data_segment(self, children) -> _DataSegment:
        return _DataSegment(children)

    def data_section(self, children) -> DataSection:
        label = IRLabel(children[0], True)
        # skip NEWLINE tokens and collect DataItems
        data_items = [child for child in children[1:] if isinstance(child, DataItem)]
        return DataSection(label, data_items)

    def data_item(self, children) -> DataItem:
        # children[0] is the DB "IDENT", children[1] is the data content, rest are NEWLINE tokens
        assert children[0] == "db", f"Expected 'db', got {children[0]}"
        item = children[1]
        if isinstance(item, IRLabel):
            return DataItem(item)

        # handle hex strings
        assert isinstance(item, str)
        assert item.startswith('x"')
        assert item.endswith('"')
        item = item.removeprefix('x"').removesuffix('"')
        item = item.replace("_", "")
        return DataItem(bytes.fromhex(item))

    def _add_revert_postamble_function(self, ctx: IRContext) -> None:
        fn = ctx.create_function("revert")
        
        fn.clear_basic_blocks()
        bb = IRBasicBlock(IRLabel("revert"), fn)
        fn.append_basic_block(bb)
        
        bb.append_instruction("revert", IRLiteral(0), IRLiteral(0))

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
            if hasattr(children[0], 'value'):
                opcode = children[0].value
            operands = []
        elif len(children) == 2:
            # Two cases: IDENT + operands_list OR "db" + operands_list
            opcode = str(children[0])
            # Handle Lark tokens  
            if hasattr(children[0], 'value'):
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


def parse_venom(source: str) -> IRContext:
    tree = VENOM_PARSER.parse(source)
    ctx = VenomTransformer().transform(tree)
    assert isinstance(ctx, IRContext)  # help mypy
    return ctx

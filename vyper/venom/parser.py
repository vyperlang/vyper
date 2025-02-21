import json

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
    %import common.CNAME
    %import common.DIGIT
    %import common.HEXDIGIT
    %import common.LETTER
    %import common.WS
    %import common.INT
    %import common.SIGNED_INT
    %import common.ESCAPED_STRING

    # Allow multiple comment styles
    COMMENT: ";" /[^\\n]*/ | "//" /[^\\n]*/ | "#" /[^\\n]*/

    start: function* data_segment?

    # TODO: consider making entry block implicit, e.g.
    # `"{" instruction+ block* "}"`
    function: "function" LABEL_IDENT "{" block* "}"

    data_segment: "data" "readonly" "{" data_section* "}"
    data_section: "dbsection" LABEL_IDENT ":" data_item+
    data_item: "db" (HEXSTR | LABEL)

    block: LABEL_IDENT ":" "\\n" statement*

    statement: (instruction | assignment) "\\n"
    assignment: VAR_IDENT "=" expr
    expr: instruction | operand
    instruction: OPCODE operands_list?

    operands_list: operand ("," operand)*

    operand: VAR_IDENT | CONST | LABEL

    CONST: SIGNED_INT
    OPCODE: CNAME
    VAR_IDENT: "%" (DIGIT|LETTER|"_"|":")+

    # handy for identifier to be an escaped string sometimes
    # (especially for machine-generated labels)
    LABEL_IDENT: (NAME | ESCAPED_STRING)
    LABEL: "@" LABEL_IDENT

    DOUBLE_QUOTE: "\\""
    NAME: (DIGIT|LETTER|"_")+
    HEXSTR: "x" DOUBLE_QUOTE (HEXDIGIT|"_")+ DOUBLE_QUOTE

    %ignore WS
    %ignore COMMENT
    """

VENOM_PARSER = Lark(VENOM_GRAMMAR)


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


def _ensure_terminated(bb):
    # Since "revert" is not considered terminal explicitly check for it to ensure basic
    # blocks are terminating
    if not bb.is_terminated:
        if any(inst.opcode == "revert" for inst in bb.instructions):
            bb.append_instruction("stop")
        # TODO: raise error if still not terminated.


def _unescape(s: str):
    """
    Unescape the escaped string. This is the inverse of `IRLabel.__repr__()`.
    """
    if s.startswith('"'):
        return json.loads(s)
    return s


class _TypedItem:
    def __init__(self, children):
        self.children = children


class _DataSegment(_TypedItem):
    pass


class VenomTransformer(Transformer):
    def start(self, children) -> IRContext:
        ctx = IRContext()
        if len(children) > 0 and isinstance(children[-1], _DataSegment):
            ctx.data_segment = children.pop().children

        funcs = children
        for fn_name, blocks in funcs:
            fn = ctx.create_function(fn_name)
            if ctx.entry_function is None:
                ctx.entry_function = fn
            fn._basic_block_dict.clear()

            for block_name, instructions in blocks:
                bb = IRBasicBlock(IRLabel(block_name, True), fn)
                fn.append_basic_block(bb)

                for instruction in instructions:
                    assert isinstance(instruction, IRInstruction)  # help mypy
                    bb.insert_instruction(instruction)

                _ensure_terminated(bb)

            _set_last_var(fn)
        _set_last_label(ctx)

        return ctx

    def function(self, children) -> tuple[str, list[tuple[str, list[IRInstruction]]]]:
        name, *blocks = children
        return name, blocks

    def statement(self, children):
        return children[0]

    def data_segment(self, children):
        return _DataSegment(children)

    def data_section(self, children):
        label = IRLabel(children[0], True)
        data_items = children[1:]
        assert all(isinstance(item, DataItem) for item in data_items)
        return DataSection(label, data_items)

    def data_item(self, children):
        item = children[0]
        if isinstance(item, IRLabel):
            return DataItem(item)
        assert item.startswith('x"')
        assert item.endswith('"')
        item = item.removeprefix('x"').removesuffix('"')
        item = item.replace("_", "")
        return DataItem(bytes.fromhex(item))

    def block(self, children) -> tuple[str, list[IRInstruction]]:
        label, *instructions = children
        return label, instructions

    def assignment(self, children) -> IRInstruction:
        to, value = children
        if isinstance(value, IRInstruction):
            value.output = to
            return value
        if isinstance(value, (IRLiteral, IRVariable)):
            return IRInstruction("store", [value], output=to)
        raise TypeError(f"Unexpected value {value} of type {type(value)}")

    def expr(self, children):
        return children[0]

    def instruction(self, children) -> IRInstruction:
        if len(children) == 1:
            opcode = children[0]
            operands = []
        else:
            assert len(children) == 2
            opcode, operands = children

        # reverse operands, venom internally represents top of stack
        # as rightmost operand
        if opcode == "invoke":
            # reverse stack arguments but not label arg
            # invoke <target> <stack arguments>
            operands = [operands[0]] + list(reversed(operands[1:]))
        # special cases: operands with labels look better un-reversed
        elif opcode not in ("jmp", "jnz", "phi"):
            operands.reverse()
        return IRInstruction(opcode, operands)

    def operands_list(self, children) -> list[IROperand]:
        return children

    def operand(self, children) -> IROperand:
        return children[0]

    def OPCODE(self, token):
        return token.value

    def LABEL_IDENT(self, label) -> str:
        return _unescape(label)

    def LABEL(self, label) -> IRLabel:
        label = _unescape(label[1:])
        return IRLabel(label, True)

    def VAR_IDENT(self, var_ident) -> IRVariable:
        return IRVariable(var_ident[1:])

    def CONST(self, val) -> IRLiteral:
        return IRLiteral(int(val))

    def CNAME(self, val) -> str:
        return val.value

    def NAME(self, val) -> str:
        return val.value


def parse_venom(source: str) -> IRContext:
    tree = VENOM_PARSER.parse(source)
    ctx = VenomTransformer().transform(tree)
    assert isinstance(ctx, IRContext)  # help mypy
    return ctx

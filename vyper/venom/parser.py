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
from vyper.venom.context import IRContext
from vyper.venom.function import IRFunction

VENOM_PARSER = Lark(
    """
    %import common.CNAME
    %import common.DIGIT
    %import common.LETTER
    %import common.WS
    %import common.INT
    %import common.SIGNED_INT
    %import common.ESCAPED_STRING

    # Allow multiple comment styles
    COMMENT: ";" /[^\\n]*/ | "//" /[^\\n]*/ | "#" /[^\\n]*/

    start: function* data_section?

    # TODO: consider making entry block implicit, e.g.
    # `"{" instruction+ block* "}"`
    function: "function" LABEL_IDENT "{" block* "}"

    data_section: "[data]" instruction*

    block: LABEL_IDENT ":" "\\n" statement*

    statement: (instruction | assignment) "\\n"
    assignment: VAR_IDENT "=" expr
    expr: instruction | operand
    instruction: OPCODE operands_list?

    operands_list: operand ("," operand)*

    operand: VAR_IDENT | CONST | LABEL

    CONST: SIGNED_INT
    OPCODE: CNAME
    VAR_IDENT: "%" NAME (":" INT)?

    # handy for identifier to be an escaped string sometimes
    # (especially for machine-generated labels)
    LABEL_IDENT: (NAME | ESCAPED_STRING)
    LABEL: "@" LABEL_IDENT

    NAME: (DIGIT|LETTER|"_")+

    %ignore WS
    %ignore COMMENT
    """
)


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


class _DataSegment:
    def __init__(self, instructions):
        self.instructions = instructions


class VenomTransformer(Transformer):
    def start(self, children) -> IRContext:
        ctx = IRContext()
        data_section = []
        if isinstance(children[-1], _DataSegment):
            data_section = children.pop().instructions
        funcs = children
        for fn_name, blocks in funcs:
            fn = ctx.create_function(fn_name)
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

        ctx.data_segment = data_section

        return ctx

    def function(self, children) -> tuple[str, list[tuple[str, list[IRInstruction]]]]:
        name, *blocks = children
        return name, blocks

    def statement(self, children):
        return children[0]

    def data_section(self, children):
        return _DataSegment(children)

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
        if opcode not in ("jmp", "jnz", "invoke", "phi"):
            # special cases: operands with labels look better un-reversed
            operands.reverse()
        return IRInstruction(opcode, operands)

    def operands_list(self, children) -> list[IROperand]:
        return children

    def operand(self, children) -> IROperand:
        return children[0]

    def OPCODE(self, token):
        return token.value

    def LABEL_IDENT(self, label) -> str:
        if label.startswith('"'):
            # unescape the escaped string
            label = json.loads(label)
        return label

    def LABEL(self, label) -> IRLabel:
        label = label[1:]
        if label.startswith('"'):
            # unescape the escaped string
            label = json.loads(label)
        return IRLabel(label, True)

    def VAR_IDENT(self, var_ident) -> IRVariable:
        parts = var_ident[1:].split(":", maxsplit=1)
        assert 1 <= len(parts) <= 2
        varname = parts[0]
        version = None
        if len(parts) > 1:
            version = parts[1]
        return IRVariable(varname, version=version)

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

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

    # TODO: make data_section optional -- `function* data_section?`
    start: function* data_section

    # TODO: consider making entry block implicit, e.g.
    # `"{" instruction+ block* "}"`
    function: "function" NAME "{" block* "}"

    data_section: "[data]" instruction*

    block: NAME ":" statement*

    statement: instruction | assignment
    assignment: VAR_IDENT "=" expr
    expr: instruction | CONST
    instruction: OPCODE operands_list?

    operands_list: operand ("," operand)*

    operand: VAR_IDENT | CONST | LABEL

    CONST: INT
    OPCODE: CNAME
    VAR_IDENT: "%" INT (":" INT)?
    LABEL: "@" NAME
    NAME: (DIGIT|LETTER|"_")+

    %ignore WS
    """
)


def _set_last_var(fn: IRFunction):
    for bb in fn.get_basic_blocks():
        for inst in bb.instructions:
            if inst.output is None:
                continue
            value = inst.output.value
            assert value.startswith("%")
            fn.last_variable = max(fn.last_variable, int(value[1:]))


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
    if not bb.is_terminated and any(inst.opcode == "revert" for inst in bb.instructions):
        bb.append_instruction("stop")


class VenomTransformer(Transformer):
    def start(self, children) -> IRContext:
        ctx = IRContext()
        funcs = children[:-1]
        data_section = children[-1]
        for fn_name, blocks in funcs:
            fn = ctx.create_function(fn_name)
            fn._basic_block_dict.clear()

            for block_name, instructions in blocks:
                bb = IRBasicBlock(IRLabel(block_name), fn)
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
        return children

    def block(self, children) -> tuple[str, list[IRInstruction]]:
        label, *instructions = children
        return label, instructions

    def assignment(self, children) -> IRInstruction:
        to, value = children
        if isinstance(value, IRInstruction):
            value.output = to
            return value
        if isinstance(value, IRLiteral):
            return IRInstruction("store", [value], output=to)
        raise TypeError(f"Unexpected value {value} of type {type(value)}")

    def expr(self, children):
        return children[0]

    def instruction(self, children) -> IRInstruction:
        if len(children) == 1:
            name = children[0]
            operands = []
        else:
            assert len(children) == 2
            name, operands = children

        # reverse operands, venom internally represents top of stack
        # as rightmost operand
        return IRInstruction(name, reversed(operands))

    def operands_list(self, children) -> list[IROperand]:
        return children

    def operand(self, children) -> IROperand:
        return children[0]

    def OPCODE(self, token):
        return token.value

    def LABEL(self, label) -> IRLabel:
        return IRLabel(label[1:])

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

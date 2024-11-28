from vyper.venom.context import IRContext
from vyper.venom.basicblock import (
    IRLabel, IRVariable, IRLiteral, IROperand, IRInstruction, IRBasicBlock
)
from lark import Lark, Transformer


VENOM_PARSER = Lark(
    '''
    %import common.CNAME
    %import common.DIGIT
    %import common.LETTER
    %import common.WS
    %import common.INT

    start: function* data_section
    function: "fn" NAME "=>" "{" block* "}"
    data_section: "data:" call*

    block: NAME ":" (call | assignment)*

    assignment: VAR_IDENT "=" expr
    expr: call | CONST
    call: CNAME operands_list

    operands_list: (operand ("," operand)*)?

    operand: VAR_IDENT | CONST | LABEL
    CONST: INT

    VAR_IDENT: "%" INT (":" INT)?
    LABEL: "@" NAME
    NAME: (DIGIT|LETTER|"_")+

    %ignore WS
    '''
)


class VenomTransformer(Transformer):
    def start(self, children) -> IRContext:
        ctx = IRContext()
        funcs = children[:-1]
        data_section = children[-1]
        for fn_name, blocks in funcs:
            fn = ctx.create_function(fn_name)
            for block_name, instructions in blocks:
                bb = IRBasicBlock(IRLabel(block_name), fn)

                for instruction in instructions:
                    bb.insert_instruction(instruction)

                # Manually insert because we need to override function entry
                fn._basic_block_dict[block_name] = bb

        ctx.data_segment = data_section

        ctx.chain_basic_blocks()

        return ctx

    def function(self, children) -> tuple[str, list[tuple[str, list[IRInstruction]]]]:
        name, *blocks = children
        return name, blocks

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
        elif isinstance(value, IRLiteral):
            return IRInstruction('store', [value], output=to)
        else:
            raise TypeError(f'Unexpected value {value} of type {type(value)}')

    def expr(self, children):
        return children[0]

    def call(self, children) -> IRInstruction:
        name, operands = children
        return IRInstruction(name, operands)

    def operands_list(self, children) -> list[IROperand]:
        return children

    def operand(self, children) -> IROperand:
        return children[0]

    def LABEL(self, label) -> IRLabel:
        return IRLabel(label[1:])

    def VAR_IDENT(self, var_ident) -> IRVariable:
        parts = var_ident[1:].split(':', maxsplit=1)
        return IRVariable(*parts)

    def CONST(self, val) -> IRLiteral:
        return IRLiteral(int(val))

    def CNAME(self, val) -> str:
        return val.value

    def NAME(self, val) -> str:
        return val.value


def parse_venom(source: str) -> IRContext:
    tree = VENOM_PARSER.parse(source)
    ctx = VenomTransformer().transform(tree)
    assert isinstance(ctx, IRContext)
    return ctx

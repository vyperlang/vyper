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
from vyper.venom.const_eval import evaluate_const_expr, try_evaluate_const_expr
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

    start: (const_def | global_label | function)*

    # Constant definitions
    const_def: "const" IDENT "=" const_expr NEWLINE+

    # Global label definitions with optional address override
    global_label: label_name ":" const_expr NEWLINE+

    function: "function" func_name "{" block_content "}"

    block_content: (label_decl | statement)*

    label_decl: (IDENT | ESCAPED_STRING) ":" ("[" tag_list "]")? NEWLINE+

    tag_list: tag ("," tag)*
    tag: IDENT

    statement: (assignment | instruction) NEWLINE+
    assignment: VAR_IDENT "=" expr
    expr: instruction | operand

    instruction: IDENT operands_list?
               | DB operands_list

    operands_list: operand ("," operand)*

    operand: VAR_IDENT | const_expr | HEXSTR

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

    # Constant expressions
    const_expr: const_atom | const_func
    const_func: IDENT "(" const_expr ("," const_expr)* ")"
    const_atom: CONST | const_ref | label_ref
    const_ref: "$" IDENT

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


class _ConstDef(_TypedItem):
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

        # Separate const defs, global labels and functions
        const_defs = []
        global_labels = []
        funcs = []

        for child in children:
            if isinstance(child, _ConstDef):
                const_defs.append(child)
            elif isinstance(child, _GlobalLabel):
                global_labels.append(child)
            else:
                funcs.append(child)

        # Process const definitions first
        for const_def in const_defs:
            name, expr = const_def.children
            value = self._evaluate_const_expr(expr, ctx.constants, ctx.global_labels)
            ctx.add_constant(name, value)

        # Process global labels
        for global_label in global_labels:
            name, expr = global_label.children
            address = self._evaluate_const_expr(expr, ctx.constants, ctx.global_labels)
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
                    current_block_address = item.address  # Will always be None now
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
                block_name, _address, instructions, tags = block_data
                bb = IRBasicBlock(IRLabel(block_name, True), fn)

                # Set is_volatile if "pinned" tag is present
                if "pinned" in tags:
                    bb.is_pinned = True

                fn.append_basic_block(bb)

                for instruction in instructions:
                    assert isinstance(instruction, IRInstruction)  # help mypy
                    # Process instruction operands to evaluate const expressions
                    processed_operands = []
                    for op in instruction.operands:
                        if isinstance(op, (str, tuple)) and not isinstance(op, IROperand):
                            # This is a const expression - evaluate it
                            if isinstance(op, str) and op.startswith("@"):
                                # This is a label reference that came from const_atom
                                # Convert it back to IRLabel
                                label_name = op[1:]
                                processed_operands.append(IRLabel(label_name, True))
                            else:
                                # Use try_evaluate to handle undefined constants
                                processed_operands.append(self._try_evaluate_const_expr(op, ctx))
                        else:
                            processed_operands.append(op)
                    # Create new instruction with evaluated operands
                    new_inst = IRInstruction(
                        instruction.opcode, processed_operands, output=instruction.output
                    )
                    new_inst.ast_source = instruction.ast_source
                    new_inst.error_msg = instruction.error_msg
                    bb.insert_instruction(new_inst)

            _set_last_var(fn)

        _set_last_label(ctx)

        return ctx

    def _evaluate_const_expr(
        self, expr, constants: dict[str, int], global_labels: dict[str, int]
    ) -> int:
        """Helper method to evaluate const expressions."""
        return evaluate_const_expr(expr, constants, global_labels)

    def _try_evaluate_const_expr(self, expr, ctx: IRContext) -> IROperand:
        """Try to evaluate const expression, returning IRLabel for unresolved parts."""
        result = try_evaluate_const_expr(
            expr, ctx.constants, ctx.global_labels, ctx.unresolved_consts, ctx.const_refs
        )
        if isinstance(result, int):
            return IRLiteral(result)
        else:
            # result is a label name for unresolved constant
            return IRLabel(result, True)

    def const_def(self, children) -> _ConstDef:
        # Filter out NEWLINE tokens
        filtered = [c for c in children if not (hasattr(c, "type") and c.type == "NEWLINE")]
        name, expr = filtered
        return _ConstDef([str(name), expr])

    def global_label(self, children) -> _GlobalLabel:
        # Filter out NEWLINE tokens
        filtered = [c for c in children if not (hasattr(c, "type") and c.type == "NEWLINE")]
        name, expr = filtered
        return _GlobalLabel([name, expr])

    def function(self, children) -> tuple[str, list]:
        name, block_content = children
        return name, block_content

    def block_content(self, children) -> list:
        # children contains label_decls and statements
        return children

    def label_decl(self, children) -> _LabelDecl:
        # children[0] is the label, optional tags, then NEWLINE tokens
        label = _unescape(str(children[0]))
        tags = []

        # Process children after the label
        for child in children[1:]:
            # Skip NEWLINE tokens
            if hasattr(child, "type") and child.type == "NEWLINE":
                continue
            elif isinstance(child, list):  # tag_list returns a list
                tags = child

        return _LabelDecl(label, None, tags)

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
        # Handle const expressions that need evaluation
        if isinstance(value, (str, tuple)):
            # This will be evaluated later in the function processing
            return IRInstruction("store", [value], output=to)  # type: ignore[list-item]
        # Handle raw integers from const_atom
        if isinstance(value, int):
            return IRInstruction("store", [IRLiteral(value)], output=to)
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

        # Process operands - evaluate const expressions if needed
        processed_operands = []
        for op in operands:
            if isinstance(op, (str, tuple)) and not isinstance(op, IROperand):
                # This is a const expression that needs evaluation
                # We need access to context, so we'll store it as-is for now
                # and process it later during function processing
                processed_operands.append(op)
            else:
                processed_operands.append(op)

        # reverse operands, venom internally represents top of stack
        # as rightmost operand
        if opcode == "invoke":
            # reverse stack arguments but not label arg
            # invoke <target> <stack arguments>
            processed_operands = [processed_operands[0]] + list(reversed(processed_operands[1:]))
        # special cases: operands with labels look better un-reversed
        elif opcode not in ("jmp", "jnz", "djmp", "phi", "db"):
            processed_operands.reverse()
        return IRInstruction(opcode, processed_operands)  # type: ignore[arg-type]

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

    def const_expr(self, children):
        # const_expr: const_atom | const_func
        return children[0]

    def const_atom(self, children):
        # const_atom: CONST | const_ref | label_ref
        child = children[0]
        if isinstance(child, IRLiteral):
            return child
        elif isinstance(child, IRLabel):
            # Return as a label reference to be evaluated later
            return f"@{child.value}"
        else:
            # Must be a const_ref (string starting with $)
            return child

    def const_ref(self, children) -> str:
        # const_ref: "$" IDENT
        return f"${children[0]}"

    def const_func(self, children):
        # const_func: IDENT "(" const_expr ("," const_expr)* ")"
        op_name = str(children[0])
        args = children[1:]

        if len(args) != 2:
            raise ValueError(f"Operation {op_name} requires exactly 2 arguments, got {len(args)}")

        # Return a tuple representing the operation
        return (op_name, args[0], args[1])


def parse_venom(source: str) -> IRContext:
    tree = VENOM_PARSER.parse(source)
    ctx = VenomTransformer().transform(tree)
    assert isinstance(ctx, IRContext)  # help mypy
    return ctx

from vyper.venom.basicblock import ConstRef, IRLabel, IRLiteral, IROperand, LabelRef
from vyper.venom.const_eval import try_evaluate_const_expr
from vyper.venom.context import IRContext


def resolve_const_operands(ctx: IRContext) -> None:
    """Resolve raw const expressions in operands to IRLiteral or IRLabel."""
    # First evaluate simple const expressions to populate ctx.constants
    for name, expr in ctx.const_expressions.items():
        if isinstance(expr, (int, IRLiteral)):
            # Simple literal
            value = expr if isinstance(expr, int) else expr.value
            ctx.constants[name] = value

    # Now resolve operands
    for fn in ctx.functions.values():
        for bb in fn.get_basic_blocks():
            for inst in bb.instructions:
                new_operands = []
                for op in inst.operands:
                    if isinstance(op, (tuple, ConstRef, LabelRef)) and not isinstance(op, IROperand):
                        # This is a raw const expression - evaluate it
                        result = try_evaluate_const_expr(
                            op,
                            ctx.constants,
                            ctx.global_labels,
                            ctx.unresolved_consts,
                            ctx.const_refs,
                        )
                        if isinstance(result, int):
                            new_operands.append(IRLiteral(result))
                        else:
                            # Return as label for unresolved expressions
                            new_operands.append(IRLabel(result, True))
                    else:
                        new_operands.append(op)
                inst.operands = new_operands

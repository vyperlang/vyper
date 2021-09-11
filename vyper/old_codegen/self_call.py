from vyper.exceptions import StateAccessViolation, StructureException
from vyper.old_codegen.context import Context
from vyper.old_codegen.lll_node import LLLnode, push_label_to_stack
from vyper.old_codegen.parser_utils import getpos, make_setter
from vyper.old_codegen.types import TupleType

_label_counter = 0


# TODO a more general way of doing this
def _generate_label(name: str) -> str:
    global _label_counter
    _label_counter += 1
    return f"label{_label_counter}"


def lll_for_self_call(stmt_expr, context: Context) -> LLLnode:
    from vyper.old_codegen.expr import Expr  # TODO rethink this circular import

    pos = getpos(stmt_expr)

    # ** Internal Call **
    # Steps:
    # - copy arguments into the soon-to-be callee
    # - allocate return buffer
    # - push jumpdest (callback ptr) and return buffer location
    # - jump to label
    # - (private function will fill return buffer and jump back)

    method_name = stmt_expr.func.attr

    pos_args_lll = [Expr(x, context).lll_node for x in stmt_expr.args]

    sig, kw_vals = context.lookup_internal_function(method_name, pos_args_lll)

    kw_args_lll = [Expr(x, context).lll_node for x in kw_vals]

    args_lll = pos_args_lll + kw_args_lll

    args_tuple_t = TupleType([x.typ for x in args_lll])
    args_as_tuple = LLLnode.from_list(["multi"] + [x for x in args_lll], typ=args_tuple_t)

    # register callee to help calculate our starting frame offset
    context.register_callee(sig.frame_size)

    if context.is_constant() and sig.mutability not in ("view", "pure"):
        raise StateAccessViolation(
            f"May not call state modifying function "
            f"'{method_name}' within {context.pp_constancy()}.",
            getpos(stmt_expr),
        )

    # TODO move me to type checker phase
    if not sig.internal:
        raise StructureException("Cannot call external functions via 'self'", stmt_expr)

    return_label = _generate_label(f"{sig.internal_function_label}_call")

    # allocate space for the return buffer
    # TODO allocate in stmt and/or expr.py
    return_buffer = (
        context.new_internal_variable(sig.return_type) if sig.return_type is not None else "pass"
    )
    return_buffer = LLLnode.from_list([return_buffer], annotation=f"{return_label}_return_buf")

    args_dst = LLLnode(sig.frame_start, typ=args_tuple_t, location="memory")
    copy_args = make_setter(args_dst, args_as_tuple, "memory", pos)

    call_sequence = [
        "seq_unchecked",
        copy_args,
        push_label_to_stack(return_label),  # pass return label to subroutine
        return_buffer,  # pass return buffer to subroutine
        ["goto", sig.internal_function_label],
        ["label", return_label],
        return_buffer,  # push return buffer location to stack
    ]

    o = LLLnode.from_list(
        call_sequence,
        typ=sig.return_type,
        location="memory",
        pos=pos,
        annotation=f"Internal Call: {method_name}",
        add_gas_estimate=sig.gas,
    )
    return o

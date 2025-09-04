import copy
import dataclasses

from vyper.codegen.core import _freshname, eval_once_check, make_setter
from vyper.codegen.ir_node import IRnode
from vyper.evm.address_space import MEMORY
from vyper.exceptions import StateAccessViolation
from vyper.semantics.types.subscriptable import TupleT


def _align_kwargs(func_t, args_ir):
    """
    Using a list of args, find the kwargs which need to be filled in by
    the compiler
    """

    # sanity check
    assert func_t.n_positional_args <= len(args_ir) <= func_t.n_total_args

    num_provided_kwargs = len(args_ir) - func_t.n_positional_args

    unprovided_kwargs = func_t.keyword_args[num_provided_kwargs:]
    return [i.default_value for i in unprovided_kwargs]


def ir_for_self_call(stmt_expr, context):
    from vyper.codegen.expr import Expr  # TODO rethink this circular import

    # ** Internal Call **
    # Steps:
    # - copy arguments into the soon-to-be callee
    # - allocate return buffer
    # - push jumpdest (callback ptr) and return buffer location
    # - jump to label
    # - (private function will fill return buffer and jump back)
    method_name = stmt_expr.func.attr
    func_t = stmt_expr.func._metadata["type"]

    pos_args_ir = [Expr(x, context).ir_node for x in stmt_expr.args]

    default_vals = _align_kwargs(func_t, pos_args_ir)
    default_vals_ir = [Expr(x, context).ir_node for x in default_vals]

    args_ir = pos_args_ir + default_vals_ir
    assert len(args_ir) == len(func_t.arguments)

    args_tuple_t = TupleT([x.typ for x in args_ir])
    args_as_tuple = IRnode.from_list(["multi"] + [x for x in args_ir], typ=args_tuple_t)

    # CMC 2023-05-17 this seems like it is already caught in typechecker
    if context.is_constant() and func_t.is_mutable:
        raise StateAccessViolation(
            f"May not call state modifying function "
            f"'{method_name}' within {context.pp_constancy()}.",
            stmt_expr,
        )

    # note: internal_function_label asserts `func_t.is_internal`.
    _label = func_t._ir_info.internal_function_label(context.is_ctor_context)
    return_label = _freshname(f"{_label}_call")

    # allocate space for the return buffer
    # TODO allocate in stmt and/or expr.py
    if func_t.return_type is not None:
        return_buffer = context.new_internal_variable(func_t.return_type)
        return_buffer.annotation = f"{return_label}_return_buf"
    else:
        return_buffer = None

    # note: dst_tuple_t != args_tuple_t
    dst_tuple_t = TupleT(tuple(func_t.argument_types))
    if context.settings.experimental_codegen:
        arg_items = ["multi"]
        frame_info = func_t._ir_info.frame_info

        for var in frame_info.frame_vars.values():
            var = copy.copy(var)
            alloca = var.alloca
            assert alloca is not None
            assert isinstance(var.pos, str)  # help mypy
            if not var.pos.startswith("$palloca"):
                continue
            newname = var.pos.replace("$palloca", "$calloca")
            var.pos = newname
            alloca = dataclasses.replace(alloca, _callsite=return_label)
            irnode = var.as_ir_node()
            irnode.passthrough_metadata["alloca"] = alloca
            irnode.passthrough_metadata["callsite_func"] = func_t
            arg_items.append(irnode)
        args_dst = IRnode.from_list(arg_items, typ=dst_tuple_t)
    else:
        # legacy
        args_dst = IRnode(func_t._ir_info.frame_info.frame_start, typ=dst_tuple_t, location=MEMORY)

    # if one of the arguments is a self call, the argument
    # buffer could get borked. to prevent against that,
    # write args to a temporary buffer until all the arguments
    # are fully evaluated.
    if args_as_tuple.contains_self_call:
        copy_args = ["seq"]
        # TODO deallocate me
        tmp_args_buf = context.new_internal_variable(dst_tuple_t)
        copy_args.append(
            # --> args evaluate here <--
            make_setter(tmp_args_buf, args_as_tuple)
        )

        copy_args.append(make_setter(args_dst, tmp_args_buf))

    else:
        copy_args = make_setter(args_dst, args_as_tuple)

    goto_op = ["goto", func_t._ir_info.internal_function_label(context.is_ctor_context)]
    # pass return buffer to subroutine
    if return_buffer is not None:
        goto_op += [return_buffer]
    # pass return label to subroutine
    goto_op.append(["symbol", return_label])

    call_sequence = ["seq"]
    call_sequence.append(eval_once_check(_freshname(stmt_expr.node_source_code)))
    call_sequence.extend([copy_args, goto_op, ["label", return_label, ["var_list"], "pass"]])
    if return_buffer is not None:
        # push return buffer location to stack
        call_sequence += [return_buffer]

    o = IRnode.from_list(
        call_sequence,
        typ=func_t.return_type,
        location=MEMORY,
        annotation=stmt_expr.get("node_source_code"),
        add_gas_estimate=func_t._ir_info.gas_estimate,
    )
    o.is_self_call = True
    o.invoked_function_ir = func_t._ir_info.func_ir
    o.passthrough_metadata["func_t"] = func_t
    o.passthrough_metadata["args_ir"] = args_ir
    return o

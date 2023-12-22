from vyper import ast as vy_ast
from vyper.codegen.core import (
    _freshname,
    data_location_to_addr_space,
    eval_once_check,
    get_element_ptr,
    make_setter,
)
from vyper.codegen.ir_node import IRnode
from vyper.evm.address_space import MEMORY
from vyper.exceptions import CompilerPanic, StateAccessViolation
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


def _get_self_ptr_for_location(node: vy_ast.Attribute, context, location):
    # resolve something like self.x.y.z to a pointer
    if isinstance(node.value, vy_ast.Name):
        # base case
        if node.value.id == "self":
            ptr = context.self_ptr(location)
        else:  # pragma: nocover
            raise CompilerPanic("unreachable!", node.value)
    else:
        # recurse
        ptr = _get_self_ptr_for_location(node.value, context, location)

    return get_element_ptr(ptr, node.attr)


def _calculate_self_ptr_requirements(call_expr, func_t, context):
    ret = []

    module_t = func_t.ast_def._parent._metadata["type"]
    if module_t == context.compilation_target:
        # we don't need to pass a pointer
        return ret

    func_expr = call_expr.func
    assert isinstance(func_expr, vy_ast.Attribute)
    pointer_expr = func_expr.value
    for location in func_t.touched_locations:
        codegen_location = data_location_to_addr_space(location)

        # self.foo.bar.baz() => pointer_expr == `self.foo.bar`
        ret.append(_get_self_ptr_for_location(pointer_expr, context, codegen_location))

    return ret


def ir_for_self_call(call_expr, context):
    from vyper.codegen.expr import Expr  # TODO rethink this circular import

    # ** Internal Call **
    # Steps:
    # - copy arguments into the soon-to-be callee
    # - allocate return buffer
    # - push jumpdest (callback ptr) and return buffer location
    # - jump to label
    # - (private function will fill return buffer and jump back)
    method_name = call_expr.func.attr
    func_t = call_expr.func._metadata["type"]

    pos_args_ir = [Expr(x, context).ir_node for x in call_expr.args]

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
            call_expr,
        )

    # note: internal_function_label asserts `func_t.is_internal`.
    _label = func_t._ir_info.internal_function_label(context.is_ctor_context)
    return_label = _freshname(f"{_label}_call")

    # allocate space for the return buffer
    # TODO allocate in stmt and/or expr.py
    if func_t.return_type is not None:
        return_buffer = IRnode.from_list(
            context.new_internal_variable(func_t.return_type),
            annotation=f"{return_label}_return_buf",
        )
    else:
        return_buffer = None

    # note: dst_tuple_t != args_tuple_t
    dst_tuple_t = TupleT(tuple(func_t.argument_types))
    args_dst = IRnode(func_t._ir_info.frame_info.frame_start, typ=dst_tuple_t, location=MEMORY)

    # if one of the arguments is a self call, the argument
    # buffer could get borked. to prevent against that,
    # write args to a temporary buffer until all the arguments
    # are fully evaluated.
    if args_as_tuple.contains_self_call:
        copy_args = ["seq"]
        # TODO deallocate me
        tmp_args_buf = IRnode(
            context.new_internal_variable(dst_tuple_t), typ=dst_tuple_t, location=MEMORY
        )
        copy_args.append(
            # --> args evaluate here <--
            make_setter(tmp_args_buf, args_as_tuple)
        )

        copy_args.append(make_setter(args_dst, tmp_args_buf))

    else:
        copy_args = make_setter(args_dst, args_as_tuple)

    goto_op = ["goto", func_t._ir_info.internal_function_label(context.is_ctor_context)]

    # if needed, pass pointers to the callee
    for self_ptr in _calculate_self_ptr_requirements(call_expr, func_t, context):
        goto_op.append(self_ptr)

    # pass return buffer to subroutine
    if return_buffer is not None:
        goto_op.append(return_buffer)

    # pass return label to subroutine
    goto_op.append(["symbol", return_label])

    call_sequence = ["seq"]
    call_sequence.append(eval_once_check(_freshname(call_expr.node_source_code)))
    call_sequence.extend([copy_args, goto_op, ["label", return_label, ["var_list"], "pass"]])
    if return_buffer is not None:
        # push return buffer location to stack
        call_sequence += [return_buffer]

    o = IRnode.from_list(
        call_sequence,
        typ=func_t.return_type,
        location=MEMORY,
        annotation=call_expr.get("node_source_code"),
        add_gas_estimate=func_t._ir_info.gas_estimate,
    )
    o.is_self_call = True
    o.passthrough_metadata["func_t"] = func_t
    o.passthrough_metadata["args_ir"] = args_ir
    return o

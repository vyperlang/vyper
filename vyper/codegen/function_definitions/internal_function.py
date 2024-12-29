from vyper import ast as vy_ast
from vyper.codegen.function_definitions.common import (
    InternalFuncIR,
    get_nonreentrant_lock,
    initialize_context,
    tag_frame_info,
)
from vyper.codegen.ir_node import IRnode
from vyper.codegen.stmt import parse_body


def generate_ir_for_internal_function(
    code: vy_ast.FunctionDef, module_ctx, is_ctor_context: bool
) -> InternalFuncIR:
    """
    Parse a internal function (FuncDef), and produce full function body.

    :param func_t: the ContractFunctionT
    :param code: ast of function
    :param compilation_target: current calling context
    :return: function body in IR
    """
    # The calling convention is:
    #   Caller fills in argument buffer
    #   Caller provides return address, return buffer on the stack
    #   Callee runs its code, fills in return buffer provided by caller
    #   Callee jumps back to caller

    # The reason caller fills argument buffer is so there is less
    # complication with passing args on the stack; the caller is better
    # suited to optimize the copy operation. Also it avoids the callee
    # having to handle default args; that is easier left to the caller
    # as well. Meanwhile, the reason the callee fills the return buffer
    # is first, similarly, the callee is more suited to optimize the copy
    # operation. Second, it allows the caller to allocate the return
    # buffer in a way which reduces the number of copies. Third, it
    # reduces the potential for bugs since it forces the caller to have
    # the return data copied into a preallocated location. Otherwise, a
    # situation like the following is easy to bork:
    #   x: T[2] = [self.generate_T(), self.generate_T()]

    func_t = code._metadata["func_type"]

    # sanity check
    assert func_t.is_internal or func_t.is_constructor

    context = initialize_context(func_t, module_ctx, is_ctor_context)

    for arg in func_t.arguments:
        # allocate a variable for every arg, setting mutability
        # to True to allow internal function arguments to be mutable
        context.new_variable(arg.name, arg.typ, is_mutable=True, internal_function=True)

    # Get nonreentrant lock
    nonreentrant_pre, nonreentrant_post = get_nonreentrant_lock(func_t)

    function_entry_label = func_t._ir_info.internal_function_label(context.is_ctor_context)
    cleanup_label = func_t._ir_info.exit_sequence_label

    stack_args = ["var_list"]
    if func_t.return_type:
        stack_args += ["return_buffer"]
    stack_args += ["return_pc"]

    body = [
        "label",
        function_entry_label,
        stack_args,
        ["seq"] + nonreentrant_pre + [parse_body(code.body, context, ensure_terminated=True)],
    ]

    cleanup_routine = [
        "label",
        cleanup_label,
        ["var_list", "return_pc"],
        ["seq"] + nonreentrant_post + [["exit_to", "return_pc"]],
    ]

    ir_node = IRnode.from_list(["seq", body, cleanup_routine])

    # tag gas estimate and frame info
    func_t._ir_info.gas_estimate = ir_node.gas
    tag_frame_info(func_t, context)

    ret = InternalFuncIR(ir_node)
    func_t._ir_info.func_ir = ret

    return ret

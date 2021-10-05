from vyper import ast as vy_ast
from vyper.ast.signatures import FunctionSignature
from vyper.old_codegen.context import Context
from vyper.old_codegen.function_definitions.utils import get_nonreentrant_lock
from vyper.old_codegen.lll_node import LLLnode
from vyper.old_codegen.parser_utils import getpos
from vyper.old_codegen.stmt import parse_body


def generate_lll_for_internal_function(
    code: vy_ast.FunctionDef, sig: FunctionSignature, context: Context
) -> LLLnode:
    """
    Parse a internal function (FuncDef), and produce full function body.

    :param sig: the FuntionSignature
    :param code: ast of function
    :param context: current calling context
    :return: function body in LLL
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

    func_type = code._metadata["type"]

    # Get nonreentrant lock

    for arg in sig.args:
        # allocate a variable for every arg, setting mutability
        # to False to comply with vyper semantics, function arguments are immutable
        context.new_variable(arg.name, arg.typ, is_mutable=False)

    nonreentrant_pre, nonreentrant_post = get_nonreentrant_lock(func_type)

    function_entry_label = sig.internal_function_label
    cleanup_label = sig.exit_sequence_label

    # jump to the label which was passed in via stack
    stop_func = LLLnode.from_list(["jump", "pass"], annotation="jump to return address")

    enter = [["label", function_entry_label]] + nonreentrant_pre

    body = [parse_body(c, context) for c in code.body]

    exit = [["label", cleanup_label]] + nonreentrant_post + [stop_func]

    return LLLnode.from_list(
        ["seq"] + enter + body + exit,
        typ=None,
        pos=getpos(code),
    )

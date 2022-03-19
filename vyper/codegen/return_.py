from typing import Any, Optional

from vyper.codegen.abi_encoder import abi_encode
from vyper.codegen.context import Context
from vyper.codegen.core import (
    calculate_type_for_external_return,
    check_assign,
    dummy_node_for_type,
    getpos,
    make_setter,
    wrap_value_for_external_return,
)
from vyper.codegen.lll_node import LLLnode
from vyper.codegen.types import get_type_for_exact_size

Stmt = Any  # mypy kludge


# Generate code for return stmt
def make_return_stmt(lll_val: LLLnode, stmt: Any, context: Context) -> Optional[LLLnode]:

    sig = context.sig

    jump_to_exit = ["exit_to", f"_sym_{sig.exit_sequence_label}"]

    _pos = getpos(stmt)

    if context.return_type is None:
        if stmt.value is not None:
            return None  # triggers an exception

    else:
        # sanity typecheck
        check_assign(dummy_node_for_type(context.return_type), lll_val)

    # helper function
    def finalize(fill_return_buffer):
        # do NOT bypass this. jump_to_exit may do important function cleanup.
        fill_return_buffer = LLLnode.from_list(
            fill_return_buffer, annotation=f"fill return buffer {sig._lll_identifier}"
        )
        cleanup_loops = "cleanup_repeat" if context.forvars else "pass"
        # NOTE: because stack analysis is incomplete, cleanup_repeat must
        # come after fill_return_buffer otherwise the stack will break
        return LLLnode.from_list(
            ["seq", fill_return_buffer, cleanup_loops, jump_to_exit],
            pos=_pos,
        )

    if context.return_type is None:
        jump_to_exit += ["return_pc"]
        return finalize(["pass"])

    if context.is_internal:
        dst = LLLnode.from_list(["return_buffer"], typ=context.return_type, location="memory")
        fill_return_buffer = make_setter(dst, lll_val, pos=_pos)
        jump_to_exit += ["return_pc"]

        return finalize(fill_return_buffer)

    else:  # return from external function

        lll_val = wrap_value_for_external_return(lll_val)

        external_return_type = calculate_type_for_external_return(context.return_type)
        maxlen = external_return_type.abi_type.size_bound()
        return_buffer_ofst = context.new_internal_variable(get_type_for_exact_size(maxlen))

        # encode_out is cleverly a sequence which does the abi-encoding and
        # also returns the length of the output as a stack element
        encode_out = abi_encode(
            return_buffer_ofst, lll_val, context, pos=_pos, returns_len=True, bufsz=maxlen
        )

        # previously we would fill the return buffer and push the location and length onto the stack
        # inside of the `seq_unchecked` thereby leaving it for the function cleanup routine expects
        # the return_ofst and return_len to be on the stack
        # CMC introduced `goto` with args so this enables us to replace `seq_unchecked` w/ `seq`
        # and then just append the arguments for the cleanup to the `jump_to_exit` list
        # check in vyper/codegen/self_call.py for an example
        jump_to_exit += [return_buffer_ofst, encode_out]  # type: ignore

        return finalize(["pass"])

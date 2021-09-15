from typing import Any, Optional

from vyper.old_codegen.abi import abi_encode, abi_type_of, lll_tuple_from_args
from vyper.old_codegen.context import Context
from vyper.old_codegen.lll_node import LLLnode
from vyper.old_codegen.parser_utils import getpos, make_setter
from vyper.old_codegen.types import TupleType, get_type_for_exact_size
from vyper.old_codegen.types.check import check_assign


def _allocate_return_buffer(context: Context) -> int:
    maxlen = abi_type_of(context.return_type).size_bound()
    return context.new_internal_variable(get_type_for_exact_size(maxlen))


Stmt = Any  # mypy kludge


# Generate code for return stmt
def make_return_stmt(lll_val: LLLnode, stmt: Any, context: Context) -> Optional[LLLnode]:

    sig = context.sig

    jump_to_exit = ["goto", sig.exit_sequence_label]

    _pos = getpos(stmt)

    if context.return_type is None:
        if stmt.value is not None:
            return None  # triggers an exception

    else:
        # sanity typecheck
        _tmp = LLLnode(-1, location="memory", typ=context.return_type)
        check_assign(_tmp, lll_val, _pos)

    # helper function
    def finalize(fill_return_buffer):
        # do NOT bypass this. jump_to_exit may do important function cleanup.
        fill_return_buffer = LLLnode.from_list(
            fill_return_buffer, annotation=f"fill return buffer {sig._lll_identifier}"
        )
        return LLLnode.from_list(
            ["seq_unchecked", fill_return_buffer, jump_to_exit], typ=None, pos=_pos,
        )

    if context.return_type is None:
        return finalize(["pass"])

    if context.is_internal:
        dst = LLLnode.from_list(["return_buffer"], typ=context.return_type, location="memory")
        fill_return_buffer = [
            "with",
            dst,
            "pass",  # return_buffer is passed on the stack by caller
            make_setter(dst, lll_val, location="memory", pos=_pos),
        ]

        return finalize(fill_return_buffer)

    # we are in an external function.
    # abi-encode the data into the return buffer and jump to the function cleanup code

    # according to the ABI spec, return types are ALWAYS tuples even
    # if only one element is being returned.
    # https://solidity.readthedocs.io/en/latest/abi-spec.html#function-selector-and-argument-encoding
    # "and the return values v_1, ..., v_k of f are encoded as
    #
    #    enc((v_1, ..., v_k))
    #    i.e. the values are combined into a tuple and encoded.
    # "
    # therefore, wrap it in a tuple if it's not already a tuple.
    # for example, `bytes` is returned as abi-encoded (bytes,)
    # and `(bytes,)` is returned as abi-encoded ((bytes,),)

    if isinstance(lll_val.typ, TupleType) and len(lll_val.typ.members) > 1:
        # returning something like (int, bytes, string)
        pass
    else:
        # `-> (bytes,)` gets returned as ((bytes,),)
        # In general `-> X` gets returned as (X,)
        # (Sorry this is so confusing. I didn't make these rules.)
        lll_val = lll_tuple_from_args([lll_val])

    return_buffer_ofst = _allocate_return_buffer(context)
    # encode_out is cleverly a sequence which does the abi-encoding and
    # also returns the length of the output as a stack element
    encode_out = abi_encode(return_buffer_ofst, lll_val, pos=_pos, returns_len=True)

    # fill the return buffer and push the location and length onto the stack
    return finalize(["seq_unchecked", encode_out, return_buffer_ofst])

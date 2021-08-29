from vyper import ast as vy_ast
from vyper.old_codegen.function_definitions.utils import get_nonreentrant_lock
from vyper.old_codegen.lll_node import LLLnode
from vyper.old_codegen.parser_utils import getpos, make_setter
from vyper.old_codegen.types import ByteArrayType, TupleType, get_size_of_type
from vyper.old_codegen.types.check import check_assign
from vyper.old_codegen.context import Context
from vyper.utils import MemoryPositions

from vyper.old_codegen.abi import lll_tuple_from_args, abi_encode, abi_type_of

# something that's compatible with new_internal_variable
class FakeType:
    def __init__(self, maxlen):
        self.size_in_bytes = maxlen

def _allocate_return_buffer(context: Context) -> int:
    maxlen = abi_type_of(context.return_type).size_bound()
    return context.new_internal_variable(FakeType(maxlen=maxlen))

# Generate return code for stmt
def make_return_stmt(lll_val: LLLnode, stmt: "Stmt", context: Context) -> LLLnode:
    _pos = getpos(stmt)

    # sanity typecheck
    _tmp = LLLnode(0, location="memory", typ=context.return_type)
    check_assign(_tmp, lll_val, _pos)

    func_type = stmt.get_ancestor(vy_ast.FunctionDef)._metadata["type"]

    _pre, nonreentrant_post = get_nonreentrant_lock(func_type)

    if context.is_internal:

        os = ["seq_unchecked"]
        # write into the return buffer,
        # unlock any non-reentrant locks
        # and JUMP out of here
        os += [abi_encode("return_buffer", lll_val, pos=_pos)]
        os += nonreentrant_post
        os += [["jump", "pass"]]

    else:
        return_buffer_ofst = _allocate_return_buffer(context)
        # abi-encode the data into the return buffer,
        # unlock any non-reentrant locks
        # and RETURN out of here

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

        # encode_out is cleverly a sequence which does the abi-encoding and
        # also returns the length of the output as a stack element
        encode_out = abi_encode(return_buffer_ofst, lll_val, pos=_pos, returns_len=True)

        # run encode_out before nonreentrant post, in case there are side-effects in encode_out
        os = ["with", "return_buffer_len", encode_out,
                ["seq"] +
                nonreentrant_post +
                [["return", return_buffer_ofst, "return_buffer_len"]]
                ]

    return LLLnode.from_list(os, typ=None, pos=_pos, valency=0)

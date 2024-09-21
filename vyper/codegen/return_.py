from typing import Any, Optional

from vyper.codegen.abi_encoder import abi_encode, abi_encoding_matches_vyper
from vyper.codegen.context import Context
from vyper.codegen.core import (
    calculate_type_for_external_return,
    check_assign,
    dummy_node_for_type,
    get_type_for_exact_size,
    make_setter,
    needs_clamp,
    wrap_value_for_external_return,
)
from vyper.codegen.ir_node import IRnode
from vyper.evm.address_space import MEMORY
from vyper.exceptions import TypeCheckFailure

Stmt = Any  # mypy kludge


# Generate code for return stmt
def make_return_stmt(ir_val: IRnode, stmt: Any, context: Context) -> Optional[IRnode]:
    func_t = context.func_t

    jump_to_exit = ["exit_to", func_t._ir_info.exit_sequence_label]

    if context.return_type is None:
        if stmt.value is not None:  # pragma: nocover
            raise TypeCheckFailure("bad return")

    else:
        # sanity typecheck
        check_assign(dummy_node_for_type(context.return_type), ir_val)

    # helper function
    # do NOT bypass this. jump_to_exit may do important function cleanup.
    def finalize(fill_return_buffer):
        fill_return_buffer = IRnode.from_list(
            fill_return_buffer, annotation=f"fill return buffer {func_t._ir_info.ir_identifier}"
        )
        cleanup_loops = "cleanup_repeat" if context.forvars else "seq"
        # NOTE: because stack analysis is incomplete, cleanup_repeat must
        # come after fill_return_buffer otherwise the stack will break
        jump_to_exit_ir = IRnode.from_list(jump_to_exit)
        return IRnode.from_list(["seq", fill_return_buffer, cleanup_loops, jump_to_exit_ir])

    if context.return_type is None:
        if context.is_internal:
            jump_to_exit += ["return_pc"]
        return finalize(["seq"])

    if context.is_internal:
        dst = IRnode.from_list(["return_buffer"], typ=context.return_type, location=MEMORY)
        fill_return_buffer = make_setter(dst, ir_val)
        jump_to_exit += ["return_pc"]

        return finalize(fill_return_buffer)

    else:  # return from external function
        external_return_type = calculate_type_for_external_return(context.return_type)
        maxlen = external_return_type.abi_type.size_bound()

        # optimize: if the value already happens to be ABI encoded in
        # memory, don't bother running abi_encode, just return the
        # buffer it is in.
        can_skip_encode = (
            abi_encoding_matches_vyper(ir_val.typ)
            and ir_val.location == MEMORY
            # ensure it has already been validated - could be
            # unvalidated ABI encoded returndata for example
            and not needs_clamp(ir_val.typ, ir_val.encoding)
        )

        if can_skip_encode:
            assert ir_val.typ.memory_bytes_required == maxlen  # type: ignore
            jump_to_exit += [ir_val, maxlen]  # type: ignore
            return finalize(["pass"])

        ir_val = wrap_value_for_external_return(ir_val)

        # general case: abi_encode the data to a newly allocated buffer
        # and return the buffer
        return_buffer_ofst = context.new_internal_variable(get_type_for_exact_size(maxlen))

        # encode_out is cleverly a sequence which does the abi-encoding and
        # also returns the length of the output as a stack element
        return_len = abi_encode(return_buffer_ofst, ir_val, context, returns_len=True, bufsz=maxlen)

        # append ofst and len to exit_to the cleanup subroutine
        jump_to_exit += [return_buffer_ofst, return_len]  # type: ignore

        return finalize(["pass"])

from vyper.codegen.abi_encoder import abi_encoding_matches_vyper
from vyper.codegen.context import Context, VariableRecord
from vyper.codegen.core import get_element_ptr, make_setter, needs_clamp
from vyper.codegen.expr import Expr
from vyper.codegen.function_definitions.common import (
    EntryPointInfo,
    ExternalFuncIR,
    get_nonreentrant_lock,
    initialize_context,
    tag_frame_info,
)
from vyper.codegen.ir_node import Encoding, IRnode
from vyper.codegen.stmt import parse_body
from vyper.evm.address_space import CALLDATA, DATA
from vyper.semantics.types import TupleT
from vyper.semantics.types.function import ContractFunctionT
from vyper.utils import calc_mem_gas


# register function args with the local calling context.
# also allocate the ones that live in memory (i.e. kwargs)
def _register_function_args(func_t: ContractFunctionT, context: Context) -> list[IRnode]:
    ret = []
    # the type of the calldata
    base_args_t = TupleT(tuple(arg.typ for arg in func_t.positional_args))

    # tuple with the abi_encoded args
    if func_t.is_constructor:
        base_args_ofst = IRnode(0, location=DATA, typ=base_args_t, encoding=Encoding.ABI)
    else:
        base_args_ofst = IRnode(4, location=CALLDATA, typ=base_args_t, encoding=Encoding.ABI)

    for i, arg in enumerate(func_t.positional_args):
        arg_ir = get_element_ptr(base_args_ofst, i)

        if needs_clamp(arg.typ, Encoding.ABI):
            # allocate a memory slot for it and copy
            dst = context.new_variable(arg.name, arg.typ, is_mutable=False)

            copy_arg = make_setter(dst, arg_ir)
            copy_arg.ast_source = arg.ast_source
            ret.append(copy_arg)
        else:
            assert abi_encoding_matches_vyper(arg.typ)
            # leave it in place
            context.vars[arg.name] = VariableRecord(
                name=arg.name,
                pos=arg_ir,
                typ=arg.typ,
                mutable=False,
                location=arg_ir.location,
                encoding=Encoding.ABI,
            )

    return ret


def _generate_kwarg_handlers(
    func_t: ContractFunctionT, context: Context
) -> dict[str, EntryPointInfo]:
    # generate kwarg handlers.
    # since they might come in thru calldata or be default,
    # allocate them in memory and then fill it in based on calldata or default,
    # depending on the ContractFunctionT
    # a kwarg handler looks like
    # (if (eq _method_id <method_id>)
    #    copy calldata args to memory
    #    write default args to memory
    #    goto external_function_common_ir

    def handler_for(calldata_kwargs, default_kwargs):
        calldata_args = func_t.positional_args + calldata_kwargs
        # create a fake type so that get_element_ptr works
        calldata_args_t = TupleT(list(arg.typ for arg in calldata_args))

        abi_sig = func_t.abi_signature_for_kwargs(calldata_kwargs)

        calldata_kwargs_ofst = IRnode(
            4, location=CALLDATA, typ=calldata_args_t, encoding=Encoding.ABI
        )

        # a sequence of statements to strictify kwargs into memory
        ret = ["seq"]

        # ensure calldata is at least of minimum length
        args_abi_t = calldata_args_t.abi_type
        calldata_min_size = args_abi_t.static_size() + 4

        # TODO optimize make_setter by using
        # TupleT(list(arg.typ for arg in calldata_kwargs + default_kwargs))
        # (must ensure memory area is contiguous)

        for i, arg_meta in enumerate(calldata_kwargs):
            k = func_t.n_positional_args + i

            lhs = context.lookup_var(arg_meta.name).as_ir_node()

            rhs = get_element_ptr(calldata_kwargs_ofst, k, array_bounds_check=False)

            copy_arg = make_setter(lhs, rhs)
            copy_arg.ast_source = arg_meta.ast_source
            ret.append(copy_arg)

        for x in default_kwargs:
            lhs = context.lookup_var(x.name).as_ir_node()
            lhs.ast_source = x.ast_source
            kw_ast_val = func_t.default_values[x.name]  # e.g. `3` in x: int = 3
            rhs = Expr(kw_ast_val, context).ir_node

            copy_arg = make_setter(lhs, rhs)
            copy_arg.ast_source = x.ast_source
            ret.append(copy_arg)

        ret.append(["goto", func_t._ir_info.external_function_base_entry_label])

        # return something we can turn into ExternalFuncIR
        return abi_sig, calldata_min_size, ret

    ret = {}

    keyword_args = func_t.keyword_args

    # allocate variable slots in memory
    for arg in keyword_args:
        context.new_variable(arg.name, arg.typ, is_mutable=False)

    for i, _ in enumerate(keyword_args):
        calldata_kwargs = keyword_args[:i]
        default_kwargs = keyword_args[i:]

        sig, calldata_min_size, ir_node = handler_for(calldata_kwargs, default_kwargs)
        assert sig not in ret
        ret[sig] = EntryPointInfo(func_t, calldata_min_size, ir_node)

    sig, calldata_min_size, ir_node = handler_for(keyword_args, [])

    assert sig not in ret
    ret[sig] = EntryPointInfo(func_t, calldata_min_size, ir_node)

    return ret


def _adjust_gas_estimate(func_t, common_ir):
    # adjust gas estimate to include cost of mem expansion
    # frame_size of external function includes all private functions called
    # (note: internal functions do not need to adjust gas estimate since
    frame_info = func_t._ir_info.frame_info

    mem_expansion_cost = calc_mem_gas(frame_info.mem_used)
    common_ir.add_gas_estimate += mem_expansion_cost
    func_t._ir_info.gas_estimate = common_ir.gas


def generate_ir_for_external_function(code, compilation_target):
    # TODO type hints:
    # def generate_ir_for_external_function(
    #    code: vy_ast.FunctionDef,
    #    compilation_target: ModuleT,
    # ) -> IRnode:
    """
    Return the IR for an external function. Returns IR for the body
    of the function, handle kwargs and exit the function. Also returns
    metadata required for `module.py` to construct the selector table.
    """
    func_t = code._metadata["func_type"]
    assert func_t.is_external or func_t.is_constructor  # sanity check

    context = initialize_context(func_t, compilation_target, func_t.is_constructor)
    nonreentrant_pre, nonreentrant_post = get_nonreentrant_lock(func_t)

    # generate handlers for base args and register the variable records
    handle_base_args = _register_function_args(func_t, context)

    # generate handlers for kwargs and register the variable records
    entry_points = _generate_kwarg_handlers(func_t, context)

    body = ["seq"]
    # once optional args have been handled,
    # generate the main body of the function
    body += handle_base_args

    body += nonreentrant_pre

    body += [parse_body(code.body, context, ensure_terminated=True)]

    # wrap the body in labeled block
    body = ["label", func_t._ir_info.external_function_base_entry_label, ["var_list"], body]

    exit_sequence = ["seq"] + nonreentrant_post
    if func_t.is_constructor:
        pass  # init func has special exit sequence generated by module.py
    elif context.return_type is None:
        exit_sequence += [["stop"]]
    else:
        exit_sequence += [["return", "ret_ofst", "ret_len"]]

    exit_sequence_args = ["var_list"]
    if context.return_type is not None:
        exit_sequence_args += ["ret_ofst", "ret_len"]
    # wrap the exit in a labeled block
    exit_ = ["label", func_t._ir_info.exit_sequence_label, exit_sequence_args, exit_sequence]

    # the ir which comprises the main body of the function,
    # besides any kwarg handling
    func_common_ir = IRnode.from_list(["seq", body, exit_], ast_source=code)

    tag_frame_info(func_t, context)

    _adjust_gas_estimate(func_t, func_common_ir)

    return ExternalFuncIR(entry_points, func_common_ir)

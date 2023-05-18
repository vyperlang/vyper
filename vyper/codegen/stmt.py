import vyper.codegen.events as events
import vyper.utils as util
from vyper import ast as vy_ast
from vyper.builtins.functions import STMT_DISPATCH_TABLE
from vyper.codegen import external_call, self_call
from vyper.codegen.context import Constancy, Context
from vyper.codegen.core import (
    LOAD,
    STORE,
    IRnode,
    append_dyn_array,
    check_assign,
    clamp,
    dummy_node_for_type,
    get_dyn_array_count,
    get_element_ptr,
    getpos,
    is_return_from_function,
    make_byte_array_copier,
    make_setter,
    pop_dyn_array,
    zero_pad,
)
from vyper.codegen.expr import Expr
from vyper.codegen.return_ import make_return_stmt
from vyper.evm.address_space import MEMORY, STORAGE
from vyper.exceptions import CompilerPanic, StructureException, TypeCheckFailure
from vyper.semantics.types import DArrayT, MemberFunctionT
from vyper.semantics.types.shortcuts import INT256_T, UINT256_T


class Stmt:
    def __init__(self, node: vy_ast.VyperNode, context: Context) -> None:
        self.stmt = node
        self.context = context
        fn = getattr(self, f"parse_{type(node).__name__}", None)
        if fn is None:
            raise TypeCheckFailure(f"Invalid statement node: {type(node).__name__}")

        with context.internal_memory_scope():
            self.ir_node = fn()

        if self.ir_node is None:
            raise TypeCheckFailure("Statement node did not produce IR")

        self.ir_node.annotation = self.stmt.get("node_source_code")
        self.ir_node.source_pos = getpos(self.stmt)

    def parse_Expr(self):
        # TODO: follow analysis modules and dispatch down to expr.py
        return Stmt(self.stmt.value, self.context).ir_node

    def parse_Pass(self):
        return IRnode.from_list("pass")

    def parse_Name(self):
        if self.stmt.id == "vdb":
            return IRnode("debugger")
        else:
            raise StructureException(f"Unsupported statement type: {type(self.stmt)}", self.stmt)

    def parse_AnnAssign(self):
        ltyp = self.stmt.target._metadata["type"]
        varname = self.stmt.target.id
        alloced = self.context.new_variable(varname, ltyp)

        assert self.stmt.value is not None
        rhs = Expr(self.stmt.value, self.context).ir_node

        lhs = IRnode.from_list(alloced, typ=ltyp, location=MEMORY)

        return make_setter(lhs, rhs)

    def parse_Assign(self):
        # Assignment (e.g. x[4] = y)
        src = Expr(self.stmt.value, self.context).ir_node
        dst = self._get_target(self.stmt.target)

        ret = ["seq"]
        overlap = len(dst.referenced_variables & src.referenced_variables) > 0
        if overlap and not dst.typ._is_prim_word:
            # there is overlap between the lhs and rhs, and the type is
            # complex - i.e., it spans multiple words. for safety, we
            # copy to a temporary buffer before copying to the destination.
            tmp = self.context.new_internal_variable(src.typ)
            tmp = IRnode.from_list(tmp, typ=src.typ, location=MEMORY)
            ret.append(make_setter(tmp, src))
            src = tmp

        ret.append(make_setter(dst, src))
        return IRnode.from_list(ret)

    def parse_If(self):
        if self.stmt.orelse:
            with self.context.block_scope():
                add_on = [parse_body(self.stmt.orelse, self.context)]
        else:
            add_on = []

        with self.context.block_scope():
            test_expr = Expr.parse_value_expr(self.stmt.test, self.context)
            body = ["if", test_expr, parse_body(self.stmt.body, self.context)] + add_on
            ir_node = IRnode.from_list(body)
        return ir_node

    def parse_Log(self):
        event = self.stmt._metadata["type"]

        args = [Expr(arg, self.context).ir_node for arg in self.stmt.value.args]

        topic_ir = []
        data_ir = []
        for arg, is_indexed in zip(args, event.indexed):
            if is_indexed:
                topic_ir.append(arg)
            else:
                data_ir.append(arg)

        return events.ir_node_for_log(self.stmt, event, topic_ir, data_ir, self.context)

    def parse_Call(self):
        # TODO use expr.func.type.is_internal once type annotations
        # are consistently available.
        is_self_function = (
            (isinstance(self.stmt.func, vy_ast.Attribute))
            and isinstance(self.stmt.func.value, vy_ast.Name)
            and self.stmt.func.value.id == "self"
        )

        if isinstance(self.stmt.func, vy_ast.Name):
            funcname = self.stmt.func.id
            return STMT_DISPATCH_TABLE[funcname].build_IR(self.stmt, self.context)

        elif isinstance(self.stmt.func, vy_ast.Attribute) and self.stmt.func.attr in (
            "append",
            "pop",
        ):
            func_type = self.stmt.func._metadata["type"]
            if isinstance(func_type, MemberFunctionT):
                darray = Expr(self.stmt.func.value, self.context).ir_node
                args = [Expr(x, self.context).ir_node for x in self.stmt.args]
                if self.stmt.func.attr == "append":
                    # sanity checks
                    assert len(args) == 1
                    arg = args[0]
                    assert isinstance(darray.typ, DArrayT)
                    check_assign(
                        dummy_node_for_type(darray.typ.value_type), dummy_node_for_type(arg.typ)
                    )

                    return append_dyn_array(darray, arg)
                else:
                    assert len(args) == 0
                    return pop_dyn_array(darray, return_popped_item=False)

        if is_self_function:
            return self_call.ir_for_self_call(self.stmt, self.context)
        else:
            return external_call.ir_for_external_call(self.stmt, self.context)

    def _assert_reason(self, test_expr, msg):
        # from parse_Raise: None passed as the assert condition
        is_raise = test_expr is None

        if isinstance(msg, vy_ast.Name) and msg.id == "UNREACHABLE":
            if is_raise:
                return IRnode.from_list(["invalid"], error_msg="raise unreachable")
            else:
                return IRnode.from_list(
                    ["assert_unreachable", test_expr], error_msg="assert unreachable"
                )

        # set constant so that revert reason str is well behaved
        try:
            tmp = self.context.constancy
            self.context.constancy = Constancy.Constant
            msg_ir = Expr(msg, self.context).ir_node
        finally:
            self.context.constancy = tmp

        # TODO this is probably useful in codegen.core
        # compare with eval_seq.
        def _get_last(ir):
            if len(ir.args) == 0:
                return ir.value
            return _get_last(ir.args[-1])

        # TODO maybe use ensure_in_memory
        if msg_ir.location != MEMORY:
            buf = self.context.new_internal_variable(msg_ir.typ)
            instantiate_msg = make_byte_array_copier(buf, msg_ir)
        else:
            buf = _get_last(msg_ir)
            if not isinstance(buf, int):
                raise CompilerPanic(f"invalid bytestring {buf}\n{self}")
            instantiate_msg = msg_ir

        # offset of bytes in (bytes,)
        method_id = util.method_id_int("Error(string)")

        # abi encode method_id + bytestring
        assert buf >= 36, "invalid buffer"
        # we don't mind overwriting other memory because we are
        # getting out of here anyway.
        _runtime_length = ["mload", buf]
        revert_seq = [
            "seq",
            instantiate_msg,
            zero_pad(buf),
            ["mstore", buf - 64, method_id],
            ["mstore", buf - 32, 0x20],
            ["revert", buf - 36, ["add", 4 + 32 + 32, ["ceil32", _runtime_length]]],
        ]
        if is_raise:
            ir_node = revert_seq
        else:
            ir_node = ["if", ["iszero", test_expr], revert_seq]
        return IRnode.from_list(ir_node, error_msg="user revert with reason")

    def parse_Assert(self):
        test_expr = Expr.parse_value_expr(self.stmt.test, self.context)

        if self.stmt.msg:
            return self._assert_reason(test_expr, self.stmt.msg)
        else:
            return IRnode.from_list(["assert", test_expr], error_msg="user assert")

    def parse_Raise(self):
        if self.stmt.exc:
            return self._assert_reason(None, self.stmt.exc)
        else:
            return IRnode.from_list(["revert", 0, 0], error_msg="user raise")

    def _check_valid_range_constant(self, arg_ast_node):
        with self.context.range_scope():
            arg_expr = Expr.parse_value_expr(arg_ast_node, self.context)
        return arg_expr

    def _get_range_const_value(self, arg_ast_node):
        arg_expr = self._check_valid_range_constant(arg_ast_node)
        return arg_expr.value

    def parse_For(self):
        with self.context.block_scope():
            if self.stmt.get("iter.func.id") == "range":
                return self._parse_For_range()
            else:
                return self._parse_For_list()

    def _parse_For_range(self):
        # TODO make sure type always gets annotated
        if "type" in self.stmt.target._metadata:
            iter_typ = self.stmt.target._metadata["type"]
        else:
            iter_typ = INT256_T

        # Get arg0
        arg0 = self.stmt.iter.args[0]
        num_of_args = len(self.stmt.iter.args)

        # Type 1 for, e.g. for i in range(10): ...
        if num_of_args == 1:
            arg0_val = self._get_range_const_value(arg0)
            start = IRnode.from_list(0, typ=iter_typ)
            rounds = arg0_val

        # Type 2 for, e.g. for i in range(100, 110): ...
        elif self._check_valid_range_constant(self.stmt.iter.args[1]).is_literal:
            arg0_val = self._get_range_const_value(arg0)
            arg1_val = self._get_range_const_value(self.stmt.iter.args[1])
            start = IRnode.from_list(arg0_val, typ=iter_typ)
            rounds = IRnode.from_list(arg1_val - arg0_val, typ=iter_typ)

        # Type 3 for, e.g. for i in range(x, x + 10): ...
        else:
            arg1 = self.stmt.iter.args[1]
            rounds = self._get_range_const_value(arg1.right)
            start = Expr.parse_value_expr(arg0, self.context)
            _, hi = start.typ.int_bounds
            start = clamp("le", start, hi + 1 - rounds)

        r = rounds if isinstance(rounds, int) else rounds.value
        if r < 1:
            return

        varname = self.stmt.target.id
        i = IRnode.from_list(self.context.fresh_varname("range_ix"), typ=UINT256_T)
        iptr = self.context.new_variable(varname, iter_typ)

        self.context.forvars[varname] = True

        loop_body = ["seq"]
        # store the current value of i so it is accessible to userland
        loop_body.append(["mstore", iptr, i])
        loop_body.append(parse_body(self.stmt.body, self.context))

        ir_node = IRnode.from_list(["repeat", i, start, rounds, rounds, loop_body])
        del self.context.forvars[varname]

        return ir_node

    def _parse_For_list(self):
        with self.context.range_scope():
            iter_list = Expr(self.stmt.iter, self.context).ir_node

        # override with type inferred at typechecking time
        # TODO investigate why stmt.target.type != stmt.iter.type.value_type
        target_type = self.stmt.target._metadata["type"]
        iter_list.typ.value_type = target_type

        # user-supplied name for loop variable
        varname = self.stmt.target.id
        loop_var = IRnode.from_list(
            self.context.new_variable(varname, target_type), typ=target_type, location=MEMORY
        )

        i = IRnode.from_list(self.context.fresh_varname("for_list_ix"), typ=UINT256_T)

        self.context.forvars[varname] = True

        ret = ["seq"]

        # list literal, force it to memory first
        if isinstance(self.stmt.iter, vy_ast.List):
            tmp_list = IRnode.from_list(
                self.context.new_internal_variable(iter_list.typ),
                typ=iter_list.typ,
                location=MEMORY,
            )
            ret.append(make_setter(tmp_list, iter_list))
            iter_list = tmp_list

        # set up the loop variable
        e = get_element_ptr(iter_list, i, array_bounds_check=False)
        body = ["seq", make_setter(loop_var, e), parse_body(self.stmt.body, self.context)]

        repeat_bound = iter_list.typ.count
        if isinstance(iter_list.typ, DArrayT):
            array_len = get_dyn_array_count(iter_list)
        else:
            array_len = repeat_bound

        ret.append(["repeat", i, 0, array_len, repeat_bound, body])

        del self.context.forvars[varname]
        return IRnode.from_list(ret)

    def parse_AugAssign(self):
        target = self._get_target(self.stmt.target)

        sub = Expr.parse_value_expr(self.stmt.value, self.context)
        if not target.typ._is_prim_word:
            # because of this check, we do not need to check for
            # make_setter references lhs<->rhs as in parse_Assign -
            # single word load/stores are atomic.
            return

        with target.cache_when_complex("_loc") as (b, target):
            rhs = Expr.parse_value_expr(
                vy_ast.BinOp(
                    left=IRnode.from_list(LOAD(target), typ=target.typ),
                    right=sub,
                    op=self.stmt.op,
                    lineno=self.stmt.lineno,
                    col_offset=self.stmt.col_offset,
                    end_lineno=self.stmt.end_lineno,
                    end_col_offset=self.stmt.end_col_offset,
                    node_source_code=self.stmt.get("node_source_code"),
                ),
                self.context,
            )
            return b.resolve(STORE(target, rhs))

    def parse_Continue(self):
        return IRnode.from_list("continue")

    def parse_Break(self):
        return IRnode.from_list("break")

    def parse_Return(self):
        ir_val = None
        if self.stmt.value is not None:
            ir_val = Expr(self.stmt.value, self.context).ir_node
        return make_return_stmt(ir_val, self.stmt, self.context)

    def _get_target(self, target):
        _dbg_expr = target

        if isinstance(target, vy_ast.Name) and target.id in self.context.forvars:
            raise TypeCheckFailure(f"Failed constancy check\n{_dbg_expr}")

        if isinstance(target, vy_ast.Tuple):
            target = Expr(target, self.context).ir_node
            for node in target.args:
                if (node.location == STORAGE and self.context.is_constant()) or not node.mutable:
                    raise TypeCheckFailure(f"Failed constancy check\n{_dbg_expr}")
            return target

        target = Expr.parse_pointer_expr(target, self.context)
        if (target.location == STORAGE and self.context.is_constant()) or not target.mutable:
            raise TypeCheckFailure(f"Failed constancy check\n{_dbg_expr}")
        return target


# Parse a statement (usually one line of code but not always)
def parse_stmt(stmt, context):
    return Stmt(stmt, context).ir_node


# check if a function body is "terminated"
# a function is terminated if it ends with a return stmt, OR,
# it ends with an if/else and both branches are terminated.
# (if not, we need to insert a terminator so that the IR is well-formed)
def _is_terminated(code):
    last_stmt = code[-1]

    if is_return_from_function(last_stmt):
        return True

    if isinstance(last_stmt, vy_ast.If):
        if last_stmt.orelse:
            return _is_terminated(last_stmt.body) and _is_terminated(last_stmt.orelse)
    return False


# codegen a list of statements
def parse_body(code, context, ensure_terminated=False):
    if not isinstance(code, list):
        return parse_stmt(code, context)

    ir_node = ["seq"]
    for stmt in code:
        ir = parse_stmt(stmt, context)
        ir_node.append(ir)

    # force using the return routine / exit_to cleanup for end of function
    if ensure_terminated and context.return_type is None and not _is_terminated(code):
        ir_node.append(parse_stmt(vy_ast.Return(value=None), context))

    # force zerovalent, even last statement
    ir_node.append("pass")  # CMC 2022-01-16 is this necessary?
    return IRnode.from_list(ir_node)

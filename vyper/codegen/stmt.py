import vyper.codegen.events as events
import vyper.utils as util
from vyper import ast as vy_ast
from vyper.builtin_functions import STMT_DISPATCH_TABLE
from vyper.codegen import external_call, self_call
from vyper.codegen.context import Constancy, Context
from vyper.codegen.core import (
    LLLnode,
    append_dyn_array,
    get_dyn_array_count,
    get_element_ptr,
    getpos,
    is_return_from_function,
    make_byte_array_copier,
    make_setter,
    pop_dyn_array,
    unwrap_location,
    zero_pad,
)
from vyper.codegen.expr import Expr
from vyper.codegen.return_ import make_return_stmt
from vyper.codegen.types import BaseType, ByteArrayType, DArrayType, parse_type
from vyper.codegen.types.convert import new_type_to_old_type
from vyper.exceptions import CompilerPanic, StructureException, TypeCheckFailure


class Stmt:
    def __init__(self, node: vy_ast.VyperNode, context: Context) -> None:
        self.stmt = node
        self.context = context
        fn = getattr(self, f"parse_{type(node).__name__}", None)
        if fn is None:
            raise TypeCheckFailure(f"Invalid statement node: {type(node).__name__}")

        with context.internal_memory_scope():
            self.lll_node = fn()

        if self.lll_node is None:
            raise TypeCheckFailure("Statement node did not produce LLL")

        self.lll_node.annotation = self.stmt.get("node_source_code")

    def parse_Expr(self):
        return Stmt(self.stmt.value, self.context).lll_node

    def parse_Pass(self):
        return LLLnode.from_list("pass", typ=None, pos=getpos(self.stmt))

    def parse_Name(self):
        if self.stmt.id == "vdb":
            return LLLnode("debugger", typ=None, pos=getpos(self.stmt))
        else:
            raise StructureException(f"Unsupported statement type: {type(self.stmt)}", self.stmt)

    def parse_AnnAssign(self):
        typ = parse_type(
            self.stmt.annotation,
            sigs=self.context.sigs,
            custom_structs=self.context.structs,
        )
        varname = self.stmt.target.id
        pos = self.context.new_variable(varname, typ, pos=self.stmt)
        if self.stmt.value is None:
            return

        sub = Expr(self.stmt.value, self.context).lll_node

        is_literal_bytes32_assign = (
            isinstance(sub.typ, ByteArrayType)
            and sub.typ.maxlen == 32
            and isinstance(typ, BaseType)
            and typ.typ == "bytes32"
            and sub.typ.is_literal
        )

        # If bytes[32] to bytes32 assignment rewrite sub as bytes32.
        if is_literal_bytes32_assign:
            sub = LLLnode(
                util.bytes_to_int(self.stmt.value.s),
                typ=BaseType("bytes32"),
                pos=getpos(self.stmt),
            )

        variable_loc = LLLnode.from_list(
            pos,
            typ=typ,
            location="memory",
            pos=getpos(self.stmt),
        )

        lll_node = make_setter(variable_loc, sub, pos=getpos(self.stmt))

        return lll_node

    def parse_Assign(self):
        # Assignment (e.g. x[4] = y)
        sub = Expr(self.stmt.value, self.context).lll_node
        target = self._get_target(self.stmt.target)

        lll_node = make_setter(target, sub, pos=getpos(self.stmt))
        lll_node.pos = getpos(self.stmt)
        return lll_node

    def parse_If(self):
        if self.stmt.orelse:
            with self.context.block_scope():
                add_on = [parse_body(self.stmt.orelse, self.context)]
        else:
            add_on = []

        with self.context.block_scope():
            test_expr = Expr.parse_value_expr(self.stmt.test, self.context)
            body = ["if", test_expr, parse_body(self.stmt.body, self.context)] + add_on
            lll_node = LLLnode.from_list(body, typ=None, pos=getpos(self.stmt))
        return lll_node

    def parse_Log(self):
        event = self.stmt._metadata["type"]

        args = [Expr(arg, self.context).lll_node for arg in self.stmt.value.args]

        topic_lll = []
        data_lll = []
        for arg, is_indexed in zip(args, event.indexed):
            if is_indexed:
                topic_lll.append(arg)
            else:
                data_lll.append(arg)

        return events.lll_node_for_log(self.stmt, event, topic_lll, data_lll, self.context)

    def parse_Call(self):
        is_self_function = (
            (isinstance(self.stmt.func, vy_ast.Attribute))
            and isinstance(self.stmt.func.value, vy_ast.Name)
            and self.stmt.func.value.id == "self"
        )

        if isinstance(self.stmt.func, vy_ast.Name):
            funcname = self.stmt.func.id
            return STMT_DISPATCH_TABLE[funcname].build_LLL(self.stmt, self.context)

        elif isinstance(self.stmt.func, vy_ast.Attribute) and self.stmt.func.attr in (
            "append",
            "pop",
        ):
            darray = Expr(self.stmt.func.value, self.context).lll_node
            args = [Expr(x, self.context).lll_node for x in self.stmt.args]
            if self.stmt.func.attr == "append":
                assert len(args) == 1
                arg = args[0]
                assert isinstance(darray.typ, DArrayType)
                assert arg.typ == darray.typ.subtype
                return append_dyn_array(darray, arg, pos=getpos(self.stmt))
            else:
                assert len(args) == 0
                return pop_dyn_array(darray, return_popped_item=False, pos=getpos(self.stmt))

        elif is_self_function:
            return self_call.lll_for_self_call(self.stmt, self.context)
        else:
            return external_call.lll_for_external_call(self.stmt, self.context)

    def _assert_reason(self, test_expr, msg):
        if isinstance(msg, vy_ast.Name) and msg.id == "UNREACHABLE":
            return LLLnode.from_list(["assert_unreachable", test_expr], typ=None, pos=getpos(msg))

        # set constant so that revert reason str is well behaved
        try:
            tmp = self.context.constancy
            self.context.constancy = Constancy.Constant
            msg_lll = Expr(msg, self.context).lll_node
        finally:
            self.context.constancy = tmp

        # TODO this is probably useful in codegen.core
        # compare with eval_seq.
        def _get_last(lll):
            if len(lll.args) == 0:
                return lll.value
            return _get_last(lll.args[-1])

        # TODO maybe use ensure_in_memory
        if msg_lll.location != "memory":
            buf = self.context.new_internal_variable(msg_lll.typ)
            instantiate_msg = make_byte_array_copier(buf, msg_lll)
        else:
            buf = _get_last(msg_lll)
            if not isinstance(buf, int):
                raise CompilerPanic(f"invalid bytestring {buf}\n{self}")
            instantiate_msg = msg_lll

        # offset of bytes in (bytes,)
        method_id = util.abi_method_id("Error(string)")

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

        if test_expr is not None:
            lll_node = ["if", ["iszero", test_expr], revert_seq]
        else:
            lll_node = revert_seq

        return LLLnode.from_list(lll_node, typ=None, pos=getpos(self.stmt))

    def parse_Assert(self):
        test_expr = Expr.parse_value_expr(self.stmt.test, self.context)
        if test_expr.typ.is_literal:
            if test_expr.value == 1:
                # skip literal assertions that always pass
                return LLLnode.from_list(["pass"], typ=None, pos=getpos(self.stmt))
            else:
                test_expr = test_expr.value

        if self.stmt.msg:
            return self._assert_reason(test_expr, self.stmt.msg)
        else:
            return LLLnode.from_list(["assert", test_expr], typ=None, pos=getpos(self.stmt))

    def parse_Raise(self):
        if self.stmt.exc:
            return self._assert_reason(None, self.stmt.exc)
        else:
            return LLLnode.from_list(["revert", 0, 0], typ=None, pos=getpos(self.stmt))

    def _check_valid_range_constant(self, arg_ast_node, raise_exception=True):
        with self.context.range_scope():
            # TODO should catch if raise_exception == False?
            arg_expr = Expr.parse_value_expr(arg_ast_node, self.context)

        is_integer_literal = (
            isinstance(arg_expr.typ, BaseType)
            and arg_expr.typ.is_literal
            and arg_expr.typ.typ in {"uint256", "int256"}
        )
        if not is_integer_literal and raise_exception:
            raise StructureException(
                "Range only accepts literal (constant) values of type uint256 or int256",
                arg_ast_node,
            )
        return is_integer_literal, arg_expr

    def _get_range_const_value(self, arg_ast_node):
        _, arg_expr = self._check_valid_range_constant(arg_ast_node)
        return arg_expr.value

    def parse_For(self):
        with self.context.block_scope():
            if self.stmt.get("iter.func.id") == "range":
                return self._parse_For_range()
            else:
                return self._parse_For_list()

    def _parse_For_range(self):
        # attempt to use the type specified by type checking, fall back to `int256`
        # this is a stopgap solution to allow uint256 - it will be properly solved
        # once we refactor type system
        iter_typ = "int256"
        if "type" in self.stmt.target._metadata:
            iter_typ = self.stmt.target._metadata["type"]._id

        # Get arg0
        arg0 = self.stmt.iter.args[0]
        num_of_args = len(self.stmt.iter.args)

        # Type 1 for, e.g. for i in range(10): ...
        if num_of_args == 1:
            arg0_val = self._get_range_const_value(arg0)
            start = LLLnode.from_list(0, typ=iter_typ, pos=getpos(self.stmt))
            rounds = arg0_val

        # Type 2 for, e.g. for i in range(100, 110): ...
        elif self._check_valid_range_constant(self.stmt.iter.args[1], raise_exception=False)[0]:
            arg0_val = self._get_range_const_value(arg0)
            arg1_val = self._get_range_const_value(self.stmt.iter.args[1])
            start = LLLnode.from_list(arg0_val, typ=iter_typ, pos=getpos(self.stmt))
            rounds = LLLnode.from_list(arg1_val - arg0_val, typ=iter_typ, pos=getpos(self.stmt))

        # Type 3 for, e.g. for i in range(x, x + 10): ...
        else:
            arg1 = self.stmt.iter.args[1]
            rounds = self._get_range_const_value(arg1.right)
            start = Expr.parse_value_expr(arg0, self.context)

        r = rounds if isinstance(rounds, int) else rounds.value
        if r < 1:
            return

        varname = self.stmt.target.id
        i = LLLnode.from_list(self.context.fresh_varname("range_ix"), typ="uint256")
        iptr = self.context.new_variable(varname, BaseType(iter_typ), pos=getpos(self.stmt))

        self.context.forvars[varname] = True

        loop_body = ["seq"]
        # store the current value of i so it is accessible to userland
        loop_body.append(["mstore", iptr, i])
        loop_body.append(parse_body(self.stmt.body, self.context))

        lll_node = LLLnode.from_list(
            ["repeat", i, start, rounds, rounds, loop_body],
            pos=getpos(self.stmt),
        )
        del self.context.forvars[varname]

        return lll_node

    def _parse_For_list(self):
        with self.context.range_scope():
            iter_list = Expr(self.stmt.iter, self.context).lll_node

        # override with type inferred at typechecking time
        # TODO investigate why stmt.target.type != stmt.iter.type.subtype
        target_type = new_type_to_old_type(self.stmt.target._metadata["type"])
        iter_list.typ.subtype = target_type

        # user-supplied name for loop variable
        varname = self.stmt.target.id
        loop_var = LLLnode.from_list(
            self.context.new_variable(varname, target_type),
            typ=target_type,
            location="memory",
        )

        i = LLLnode.from_list(self.context.fresh_varname("for_list_ix"), typ="uint256")

        self.context.forvars[varname] = True

        ret = ["seq"]

        # list literal, force it to memory first
        if isinstance(self.stmt.iter, vy_ast.List):
            tmp_list = LLLnode.from_list(
                self.context.new_internal_variable(iter_list.typ),
                typ=iter_list.typ,
                location="memory",
            )
            ret.append(make_setter(tmp_list, iter_list, pos=getpos(self.stmt)))
            iter_list = tmp_list

        # set up the loop variable
        loop_var_ast = getpos(self.stmt.target)
        e = get_element_ptr(iter_list, i, array_bounds_check=False, pos=loop_var_ast)
        body = [
            "seq",
            make_setter(loop_var, e, pos=loop_var_ast),
            parse_body(self.stmt.body, self.context),
        ]

        repeat_bound = iter_list.typ.count
        if isinstance(iter_list.typ, DArrayType):
            array_len = get_dyn_array_count(iter_list)
        else:
            array_len = repeat_bound

        ret.append(["repeat", i, 0, array_len, repeat_bound, body])

        del self.context.forvars[varname]
        return LLLnode.from_list(ret, pos=getpos(self.stmt))

    def parse_AugAssign(self):
        target = self._get_target(self.stmt.target)
        sub = Expr.parse_value_expr(self.stmt.value, self.context)
        if not isinstance(target.typ, BaseType):
            return
        if target.location == "storage":
            lll_node = Expr.parse_value_expr(
                vy_ast.BinOp(
                    left=LLLnode.from_list(["sload", "_stloc"], typ=target.typ, pos=target.pos),
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
            return LLLnode.from_list(
                ["with", "_stloc", target, ["sstore", "_stloc", unwrap_location(lll_node)]],
                typ=None,
                pos=getpos(self.stmt),
            )
        elif target.location == "memory":
            lll_node = Expr.parse_value_expr(
                vy_ast.BinOp(
                    left=LLLnode.from_list(["mload", "_mloc"], typ=target.typ, pos=target.pos),
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
            return LLLnode.from_list(
                ["with", "_mloc", target, ["mstore", "_mloc", unwrap_location(lll_node)]],
                typ=None,
                pos=getpos(self.stmt),
            )

    def parse_Continue(self):
        return LLLnode.from_list("continue", typ=None, pos=getpos(self.stmt))

    def parse_Break(self):
        return LLLnode.from_list("break", typ=None, pos=getpos(self.stmt))

    def parse_Return(self):
        lll_val = None
        if self.stmt.value is not None:
            lll_val = Expr(self.stmt.value, self.context).lll_node
        return make_return_stmt(lll_val, self.stmt, self.context)

    def _get_target(self, target):
        _dbg_expr = target

        if isinstance(target, vy_ast.Name) and target.id in self.context.forvars:
            raise TypeCheckFailure(f"Failed constancy check\n{_dbg_expr}")

        if isinstance(target, vy_ast.Tuple):
            target = Expr(target, self.context).lll_node
            for node in target.args:
                if (node.location == "storage" and self.context.is_constant()) or not node.mutable:
                    raise TypeCheckFailure(f"Failed constancy check\n{_dbg_expr}")
            return target

        target = Expr.parse_pointer_expr(target, self.context)
        if (target.location == "storage" and self.context.is_constant()) or not target.mutable:
            raise TypeCheckFailure(f"Failed constancy check\n{_dbg_expr}")
        return target


# Parse a statement (usually one line of code but not always)
def parse_stmt(stmt, context):
    return Stmt(stmt, context).lll_node


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

    lll_node = ["seq"]
    for stmt in code:
        lll = parse_stmt(stmt, context)
        lll_node.append(lll)

    # force using the return routine / exit_to cleanup for end of function
    if ensure_terminated and context.return_type is None and not _is_terminated(code):
        lll_node.append(parse_stmt(vy_ast.Return(value=None), context))

    # force zerovalent, even last statement
    lll_node.append("pass")  # CMC 2022-01-16 is this necessary?
    return LLLnode.from_list(lll_node, pos=getpos(code[0]) if code else None)

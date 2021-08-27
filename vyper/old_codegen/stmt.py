import vyper.old_codegen.events as events
from vyper import ast as vy_ast
from vyper.builtin_functions import STMT_DISPATCH_TABLE
from vyper.exceptions import StructureException, TypeCheckFailure
from vyper.old_codegen import external_call, self_call
from vyper.old_codegen.context import Context
from vyper.old_codegen.expr import Expr
from vyper.old_codegen.parser_utils import (
    LLLnode,
    getpos,
    make_byte_array_copier,
    make_setter,
    unwrap_location,
    zero_pad,
)
from vyper.old_codegen.return_ import gen_tuple_return, make_return_stmt
from vyper.old_codegen.types import (
    BaseType,
    ByteArrayLike,
    ByteArrayType,
    ListType,
    NodeType,
    StructType,
    TupleType,
    get_size_of_type,
    parse_type,
)
from vyper.utils import SizeLimits, bytes_to_int, fourbytes_to_int, keccak256


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
            self.stmt.annotation, location="memory", custom_structs=self.context.structs,
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
                bytes_to_int(self.stmt.value.s), typ=BaseType("bytes32"), pos=getpos(self.stmt),
            )

        variable_loc = LLLnode.from_list(pos, typ=typ, location="memory", pos=getpos(self.stmt),)
        lll_node = make_setter(variable_loc, sub, "memory", pos=getpos(self.stmt))

        return lll_node

    def parse_Assign(self):
        # Assignment (e.g. x[4] = y)
        sub = Expr(self.stmt.value, self.context).lll_node
        target = self._get_target(self.stmt.target)
        lll_node = make_setter(target, sub, target.location, pos=getpos(self.stmt))
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

        # do this BEFORE evaluating args to LLL to protect the buffer
        # from internal call clobbering
        buf, _len = events.allocate_buffer_for_log(event, self.context)

        args = [Expr(arg, self.context).lll_node for arg in self.stmt.value.args]

        topic_lll = []
        data_lll = []
        for arg, is_indexed in zip(args, event.indexed):
            if is_indexed:
                topic_lll.append(arg)
            else:
                data_lll.append(arg)

        return events.lll_node_for_log(
            self.stmt, buf, _len, event, topic_lll, data_lll, self.context
        )

    def parse_Call(self):
        is_self_function = (
            (isinstance(self.stmt.func, vy_ast.Attribute))
            and isinstance(self.stmt.func.value, vy_ast.Name)
            and self.stmt.func.value.id == "self"
        )

        if isinstance(self.stmt.func, vy_ast.Name):
            funcname = self.stmt.func.id
            return STMT_DISPATCH_TABLE[funcname].build_LLL(self.stmt, self.context)
        elif is_self_function:
            return self_call.make_call(self.stmt, self.context)
        else:
            return external_call.make_external_call(self.stmt, self.context)

    def _assert_reason(self, test_expr, msg):
        if isinstance(msg, vy_ast.Name) and msg.id == "UNREACHABLE":
            return LLLnode.from_list(["assert_unreachable", test_expr], typ=None, pos=getpos(msg))

        reason_str_type = ByteArrayType(len(msg.value.strip()))

        sig_placeholder = self.context.new_internal_variable(BaseType(32))
        arg_placeholder = self.context.new_internal_variable(BaseType(32))
        placeholder_bytes = Expr(msg, self.context).lll_node

        method_id = fourbytes_to_int(keccak256(b"Error(string)")[:4])

        revert_seq = [
            "seq",
            ["mstore", sig_placeholder, method_id],
            ["mstore", arg_placeholder, 32],
            placeholder_bytes,
            ["revert", sig_placeholder + 28, int(4 + get_size_of_type(reason_str_type) * 32)],
        ]
        if test_expr:
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
            return self._assert_reason(0, self.stmt.exc)
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
        # once we refactor `vyper.parser`
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
        pos = self.context.new_variable(varname, BaseType(iter_typ), pos=getpos(self.stmt))
        self.context.forvars[varname] = True
        lll_node = LLLnode.from_list(
            ["repeat", pos, start, rounds, parse_body(self.stmt.body, self.context)],
            typ=None,
            pos=getpos(self.stmt),
        )
        del self.context.forvars[varname]

        return lll_node

    def _parse_For_list(self):
        with self.context.range_scope():
            iter_list_node = Expr(self.stmt.iter, self.context).lll_node
        if not isinstance(iter_list_node.typ.subtype, BaseType):  # Sanity check on list subtype.
            return

        iter_var_type = (
            self.context.vars.get(self.stmt.iter.id).typ
            if isinstance(self.stmt.iter, vy_ast.Name)
            else None
        )
        subtype = BaseType(self.stmt.target._metadata["type"]._id)
        iter_list_node.typ.subtype = subtype
        varname = self.stmt.target.id
        value_pos = self.context.new_variable(varname, subtype)
        i_pos = self.context.new_internal_variable(subtype)
        self.context.forvars[varname] = True

        # Is a list that is already allocated to memory.
        if iter_var_type:
            iter_var = self.context.vars.get(self.stmt.iter.id)
            if iter_var.location == "calldata":
                fetcher = "calldataload"
            elif iter_var.location == "memory":
                fetcher = "mload"
            else:
                return
            body = [
                "seq",
                [
                    "mstore",
                    value_pos,
                    [fetcher, ["add", iter_var.pos, ["mul", ["mload", i_pos], 32]]],
                ],
                parse_body(self.stmt.body, self.context),
            ]
            lll_node = LLLnode.from_list(
                ["repeat", i_pos, 0, iter_var.size, body], typ=None, pos=getpos(self.stmt)
            )

        # List gets defined in the for statement.
        elif isinstance(self.stmt.iter, vy_ast.List):
            # Allocate list to memory.
            count = iter_list_node.typ.count
            tmp_list = LLLnode.from_list(
                obj=self.context.new_internal_variable(ListType(subtype, count)),
                typ=ListType(subtype, count),
                location="memory",
            )
            setter = make_setter(tmp_list, iter_list_node, "memory", pos=getpos(self.stmt))
            body = [
                "seq",
                ["mstore", value_pos, ["mload", ["add", tmp_list, ["mul", ["mload", i_pos], 32]]]],
                parse_body(self.stmt.body, self.context),
            ]
            lll_node = LLLnode.from_list(
                ["seq", setter, ["repeat", i_pos, 0, count, body]], typ=None, pos=getpos(self.stmt)
            )

        # List contained in storage.
        elif isinstance(self.stmt.iter, vy_ast.Attribute):
            count = iter_list_node.typ.count
            body = [
                "seq",
                ["mstore", value_pos, ["sload", ["add", iter_list_node, ["mload", i_pos]]]],
                parse_body(self.stmt.body, self.context),
            ]
            lll_node = LLLnode.from_list(
                ["seq", ["repeat", i_pos, 0, count, body]], typ=None, pos=getpos(self.stmt)
            )

        # this kind of open access to the vars dict should be disallowed.
        # we should use member functions to provide an API for these kinds
        # of operations.
        del self.context.forvars[varname]
        return lll_node

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
        if self.context.return_type is None:
            if self.stmt.value:
                return
            return LLLnode.from_list(
                make_return_stmt(self.stmt, self.context, 0, 0),
                typ=None,
                pos=getpos(self.stmt),
                valency=0,
            )

        sub = Expr(self.stmt.value, self.context).lll_node

        # Returning a value (most common case)
        if isinstance(sub.typ, BaseType):
            sub = unwrap_location(sub)

            if sub.typ.is_literal and (
                self.context.return_type.typ == sub.typ
                or "int" in self.context.return_type.typ
                and "int" in sub.typ.typ
            ):  # noqa: E501
                if SizeLimits.in_bounds(self.context.return_type.typ, sub.value):
                    return LLLnode.from_list(
                        [
                            "seq",
                            ["mstore", 0, sub],
                            make_return_stmt(self.stmt, self.context, 0, 32),
                        ],
                        typ=None,
                        pos=getpos(self.stmt),
                        valency=0,
                    )
            elif isinstance(sub.typ, BaseType):
                return LLLnode.from_list(
                    ["seq", ["mstore", 0, sub], make_return_stmt(self.stmt, self.context, 0, 32)],
                    typ=None,
                    pos=getpos(self.stmt),
                    valency=0,
                )
            return
        # Returning a byte array
        elif isinstance(sub.typ, ByteArrayLike):
            if not sub.typ.eq_base(self.context.return_type):
                return
            if sub.typ.maxlen > self.context.return_type.maxlen:
                return

            # loop memory has to be allocated first.
            loop_memory_position = self.context.new_internal_variable(typ=BaseType("uint256"))
            # len & bytez placeholder have to be declared after each other at all times.
            len_placeholder = self.context.new_internal_variable(BaseType("uint256"))
            bytez_placeholder = self.context.new_internal_variable(sub.typ)

            if sub.location in ("storage", "memory"):
                return LLLnode.from_list(
                    [
                        "seq",
                        make_byte_array_copier(
                            LLLnode(bytez_placeholder, location="memory", typ=sub.typ),
                            sub,
                            pos=getpos(self.stmt),
                        ),
                        zero_pad(bytez_placeholder),
                        ["mstore", len_placeholder, 32],
                        make_return_stmt(
                            self.stmt,
                            self.context,
                            len_placeholder,
                            ["ceil32", ["add", ["mload", bytez_placeholder], 64]],
                            loop_memory_position=loop_memory_position,
                        ),
                    ],
                    typ=None,
                    pos=getpos(self.stmt),
                    valency=0,
                )
            return

        elif isinstance(sub.typ, ListType):
            loop_memory_position = self.context.new_internal_variable(typ=BaseType("uint256"))
            if sub.location == "memory" and sub.value != "multi":
                return LLLnode.from_list(
                    make_return_stmt(
                        self.stmt,
                        self.context,
                        sub,
                        get_size_of_type(self.context.return_type) * 32,
                        loop_memory_position=loop_memory_position,
                    ),
                    typ=None,
                    pos=getpos(self.stmt),
                    valency=0,
                )
            else:
                new_sub = LLLnode.from_list(
                    self.context.new_internal_variable(self.context.return_type),
                    typ=self.context.return_type,
                    location="memory",
                )
                setter = make_setter(new_sub, sub, "memory", pos=getpos(self.stmt))
                return LLLnode.from_list(
                    [
                        "seq",
                        setter,
                        make_return_stmt(
                            self.stmt,
                            self.context,
                            new_sub,
                            get_size_of_type(self.context.return_type) * 32,
                            loop_memory_position=loop_memory_position,
                        ),
                    ],
                    typ=None,
                    pos=getpos(self.stmt),
                )

        # Returning a struct
        elif isinstance(sub.typ, StructType):
            retty = self.context.return_type
            if isinstance(retty, StructType) and retty.name == sub.typ.name:
                return gen_tuple_return(self.stmt, self.context, sub)

        # Returning a tuple.
        elif isinstance(sub.typ, TupleType):
            if not isinstance(self.context.return_type, TupleType):
                return

            if len(self.context.return_type.members) != len(sub.typ.members):
                return

            # check return type matches, sub type.
            for i, ret_x in enumerate(self.context.return_type.members):
                s_member = sub.typ.members[i]
                sub_type = s_member if isinstance(s_member, NodeType) else s_member.typ
                if type(sub_type) is not type(ret_x):
                    return
            return gen_tuple_return(self.stmt, self.context, sub)

    def _get_target(self, target):
        if isinstance(target, vy_ast.Name) and target.id in self.context.forvars:
            raise TypeCheckFailure("Failed for-loop constancy check")

        if isinstance(target, vy_ast.Tuple):
            target = Expr(target, self.context).lll_node
            for node in target.args:
                if (node.location == "storage" and self.context.is_constant()) or not node.mutable:
                    raise TypeCheckFailure("Failed for-loop constancy check")
            return target

        target = Expr.parse_variable_location(target, self.context)
        if (target.location == "storage" and self.context.is_constant()) or not target.mutable:
            raise TypeCheckFailure("Failed for-loop constancy check")
        return target


# Parse a statement (usually one line of code but not always)
def parse_stmt(stmt, context):
    return Stmt(stmt, context).lll_node


# Parse a piece of code
def parse_body(code, context):
    if not isinstance(code, list):
        return parse_stmt(code, context)

    lll_node = ["seq"]
    for stmt in code:
        lll = parse_stmt(stmt, context)
        lll_node.append(lll)
    lll_node.append("pass")  # force zerovalent, even last statement
    return LLLnode.from_list(lll_node, pos=getpos(code[0]) if code else None)

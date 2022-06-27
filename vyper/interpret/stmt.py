import vyper.utils as util
from vyper import ast as vy_ast
from vyper.address_space import MEMORY, STORAGE
from vyper.builtin_functions import STMT_DISPATCH_TABLE
from vyper.exceptions import CompilerPanic, StructureException, TypeCheckFailure
from vyper.interpret.expr import Expr

class InterpreterContext:
    pass

class Stmt:
    def __init__(self, node: vy_ast.VyperNode, context: InterpreterContext) -> None:
        self.stmt = node
        self.context = context

    def interpret(self):
        fn = getattr(self, f"parse_{type(self.stmt).__name__}", None)
        if fn is None:
            raise TypeCheckFailure(f"Invalid statement node: {type(stmt).__name__}")
        return fn(self.stmt)

    def parse_Expr(self, stmt):
        Expr(stmt.value, self.context).interpret()

    def parse_Pass(self, stmt):
        pass

    def parse_Name(self, stmt):
        raise Exception("parse_Name")
        #self.vars[self.stmt.id]

    def parse_AnnAssign(self, stmt):
        typ = self.context.global_ctx.parse_type(self.stmt.annotation)
        varname = self.stmt.target.id

        if stmt.value is None:
            raise Exception("bad AnnAssign")

        val = Expr(stmt.value, self.context).interpret()

        self.context.set_var(varname, val)

    def parse_Assign(self, stmt):
        rhs = Expr(stmt.value, self.context).interpret()
        self.vars[stmt.target.id] = rhs

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

        args = [Expr(arg, self.context).interpret() for arg in stmt.value.args]

        topic_ir = []
        data_ir = []
        for arg, is_indexed in zip(args, event.indexed):
            if is_indexed:
                topic_ir.append(arg)
            else:
                data_ir.append(arg)

        return events.ir_node_for_log(self.stmt, event, topic_ir, data_ir, self.context)

    def _assert_reason(self, test_expr, msg):
        if isinstance(msg, vy_ast.Name) and msg.id == "UNREACHABLE":
            return IRnode.from_list(["assert_unreachable", test_expr], error_msg="assert unreachable")

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
            ir_node = ["if", ["iszero", test_expr], revert_seq]
        else:
            ir_node = revert_seq

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
            start = IRnode.from_list(0, typ=iter_typ)
            rounds = arg0_val

        # Type 2 for, e.g. for i in range(100, 110): ...
        elif self._check_valid_range_constant(self.stmt.iter.args[1]).typ.is_literal:
            arg0_val = self._get_range_const_value(arg0)
            arg1_val = self._get_range_const_value(self.stmt.iter.args[1])
            start = IRnode.from_list(arg0_val, typ=iter_typ)
            rounds = IRnode.from_list(arg1_val - arg0_val, typ=iter_typ)

        # Type 3 for, e.g. for i in range(x, x + 10): ...
        else:
            arg1 = self.stmt.iter.args[1]
            rounds = self._get_range_const_value(arg1.right)
            start = Expr.parse_value_expr(arg0, self.context)

        r = rounds if isinstance(rounds, int) else rounds.value
        if r < 1:
            return

        varname = self.stmt.target.id
        i = IRnode.from_list(self.context.fresh_varname("range_ix"), typ="uint256")
        iptr = self.context.new_variable(varname, BaseType(iter_typ))

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
        # TODO investigate why stmt.target.type != stmt.iter.type.subtype
        target_type = new_type_to_old_type(self.stmt.target._metadata["type"])
        iter_list.typ.subtype = target_type

        # user-supplied name for loop variable
        varname = self.stmt.target.id
        loop_var = IRnode.from_list(
            self.context.new_variable(varname, target_type), typ=target_type, location=MEMORY
        )

        i = IRnode.from_list(self.context.fresh_varname("for_list_ix"), typ="uint256")

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
        if isinstance(iter_list.typ, DArrayType):
            array_len = get_dyn_array_count(iter_list)
        else:
            array_len = repeat_bound

        ret.append(["repeat", i, 0, array_len, repeat_bound, body])

        del self.context.forvars[varname]
        return IRnode.from_list(ret)

    def parse_AugAssign(self):
        target = self._get_target(self.stmt.target)
        sub = Expr.parse_value_expr(self.stmt.value, self.context)
        if not isinstance(target.typ, BaseType):
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

    def parse_Return(self, stmt):
        val = Expr(stmt.value, self.context).interpret()
        return val

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

import vyper.codegen.events as events
import vyper.utils as util
from vyper import ast as vy_ast
from vyper.codegen.context import Constancy, Context
from vyper.codegen.core import (
    LOAD,
    STORE,
    IRnode,
    clamp_le,
    get_dyn_array_count,
    get_element_ptr,
    make_byte_array_copier,
    make_setter,
    zero_pad,
)
from vyper.codegen.expr import Expr
from vyper.codegen.return_ import make_return_stmt
from vyper.evm.address_space import MEMORY, STORAGE
from vyper.exceptions import (
    CodegenPanic,
    CompilerPanic,
    StructureException,
    TypeCheckFailure,
    tag_exceptions,
)
from vyper.semantics.types import DArrayT
from vyper.semantics.types.shortcuts import UINT256_T


class Stmt:
    def __init__(self, node: vy_ast.VyperNode, context: Context) -> None:
        self.stmt = node
        self.context = context

        fn_name = f"parse_{type(node).__name__}"
        with tag_exceptions(node, fallback_exception_type=CodegenPanic, note=fn_name):
            fn = getattr(self, fn_name)
            with context.internal_memory_scope():
                self.ir_node = fn()

            assert isinstance(self.ir_node, IRnode), self.ir_node

        self.ir_node.annotation = self.stmt.get("node_source_code")
        self.ir_node.ast_source = self.stmt

    def parse_Expr(self):
        return Expr(self.stmt.value, self.context, is_stmt=True).ir_node

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
        with self.context.block_scope():
            test_expr = Expr.parse_value_expr(self.stmt.test, self.context)
            body = ["if", test_expr, parse_body(self.stmt.body, self.context)]

        if self.stmt.orelse:
            with self.context.block_scope():
                body.extend([parse_body(self.stmt.orelse, self.context)])

        return IRnode.from_list(body)

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
            if not isinstance(buf, int):  # pragma: nocover
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

    def parse_For(self):
        with self.context.block_scope():
            if self.stmt.get("iter.func.id") == "range":
                return self._parse_For_range()
            else:
                return self._parse_For_list()

    def _parse_For_range(self):
        assert "type" in self.stmt.target.target._metadata
        target_type = self.stmt.target.target._metadata["type"]

        range_call: vy_ast.Call = self.stmt.iter
        assert isinstance(range_call, vy_ast.Call)

        with self.context.range_scope():
            args = [Expr.parse_value_expr(arg, self.context) for arg in range_call.args]
            if len(args) == 1:
                start = IRnode.from_list(0, typ=target_type)
                end = args[0]
            elif len(args) == 2:
                start, end = args
            else:  # pragma: nocover
                raise TypeCheckFailure("unreachable")

            kwargs = {
                s.arg: Expr.parse_value_expr(s.value, self.context) for s in range_call.keywords
            }

        if "bound" in kwargs:
            with end.cache_when_complex("end") as (b1, end):
                # note: the check for rounds<=rounds_bound happens in asm
                # generation for `repeat`.
                clamped_start = clamp_le(start, end, target_type.is_signed)
                rounds = b1.resolve(IRnode.from_list(["sub", end, clamped_start]))
            rounds_bound = kwargs.pop("bound").int_value()
        else:
            rounds = end.int_value() - start.int_value()
            rounds_bound = rounds

        assert len(kwargs) == 0  # sanity check stray keywords

        if rounds_bound < 1:  # pragma: nocover
            raise TypeCheckFailure("unreachable: unchecked 0 bound")

        varname = self.stmt.target.target.id
        i = IRnode.from_list(self.context.fresh_varname("range_ix"), typ=target_type)
        iptr = self.context.new_variable(varname, target_type)

        self.context.forvars[varname] = True

        loop_body = ["seq"]
        # store the current value of i so it is accessible to userland
        loop_body.append(["mstore", iptr, i])
        loop_body.append(parse_body(self.stmt.body, self.context))

        # NOTE: codegen for `repeat` inserts an assertion that
        # (gt rounds_bound rounds). note this also covers the case where
        # rounds < 0.
        # if we ever want to remove that, we need to manually add the assertion
        # where it makes sense.
        ir_node = IRnode.from_list(
            ["repeat", i, start, rounds, rounds_bound, loop_body], error_msg="range() bounds check"
        )
        del self.context.forvars[varname]

        return ir_node

    def _parse_For_list(self):
        with self.context.range_scope():
            iter_list = Expr(self.stmt.iter, self.context).ir_node

        target_type = self.stmt.target.target._metadata["type"]
        assert target_type == iter_list.typ.value_type

        # user-supplied name for loop variable
        varname = self.stmt.target.target.id
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
        right = Expr.parse_value_expr(self.stmt.value, self.context)

        if not target.typ._is_prim_word:
            # because of this check, we do not need to check for
            # make_setter references lhs<->rhs as in parse_Assign -
            # single word load/stores are atomic.
            raise TypeCheckFailure("unreachable")

        with target.cache_when_complex("_loc") as (b, target):
            left = IRnode.from_list(LOAD(target), typ=target.typ)
            new_val = Expr.handle_binop(self.stmt.op, left, right, self.context)
            return b.resolve(STORE(target, new_val))

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

    if last_stmt.is_terminus:
        return True

    if isinstance(last_stmt, vy_ast.If):
        if last_stmt.orelse:
            return _is_terminated(last_stmt.body) and _is_terminated(last_stmt.orelse)
    return False


# codegen a list of statements
def parse_body(code, context, ensure_terminated=False):
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

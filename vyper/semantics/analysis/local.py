from typing import Optional

from vyper import ast as vy_ast
from vyper.ast.metadata import NodeMetadata
from vyper.ast.validation import validate_call_args
from vyper.exceptions import (
    ExceptionList,
    FunctionDeclarationException,
    ImmutableViolation,
    InvalidLiteral,
    InvalidOperation,
    InvalidType,
    IteratorException,
    NonPayableViolation,
    StateAccessViolation,
    StructureException,
    TypeCheckFailure,
    TypeMismatch,
    VariableDeclarationException,
    VyperException,
)
from vyper.semantics.analysis.base import VarInfo
from vyper.semantics.analysis.common import VyperNodeVisitorBase
from vyper.semantics.analysis.utils import (
    get_common_types,
    get_exact_type_from_node,
    get_expr_info,
    get_possible_types_from_node,
    validate_expected_type,
)
from vyper.semantics.data_locations import DataLocation

# TODO consolidate some of these imports
from vyper.semantics.environment import CONSTANT_ENVIRONMENT_VARS, MUTABLE_ENVIRONMENT_VARS
from vyper.semantics.namespace import get_namespace
from vyper.semantics.types import (
    TYPE_T,
    AddressT,
    BoolT,
    DArrayT,
    EnumT,
    EventT,
    HashMapT,
    IntegerT,
    SArrayT,
    StringT,
    StructT,
    TupleT,
    VyperType,
    _BytestringT,
    is_type_t,
)
from vyper.semantics.types.function import ContractFunctionT, MemberFunctionT, StateMutability
from vyper.semantics.types.utils import type_from_annotation


def validate_functions(vy_module: vy_ast.Module) -> None:
    """Analyzes a vyper ast and validates the function-level namespaces."""

    err_list = ExceptionList()
    namespace = get_namespace()
    for node in vy_module.get_children(vy_ast.FunctionDef):
        with namespace.enter_scope():
            try:
                FunctionNodeVisitor(vy_module, node, namespace)
            except VyperException as e:
                err_list.append(e)

    err_list.raise_if_not_empty()


def _is_terminus_node(node: vy_ast.VyperNode) -> bool:
    if getattr(node, "_is_terminus", None):
        return True
    if isinstance(node, vy_ast.Expr) and isinstance(node.value, vy_ast.Call):
        func = get_exact_type_from_node(node.value.func)
        if getattr(func, "_is_terminus", None):
            return True
    return False


def check_for_terminus(node_list: list) -> bool:
    if next((i for i in node_list if _is_terminus_node(i)), None):
        return True
    for node in [i for i in node_list if isinstance(i, vy_ast.If)][::-1]:
        if not node.orelse or not check_for_terminus(node.orelse):
            continue
        if not check_for_terminus(node.body):
            continue
        return True
    return False


def _check_iterator_modification(
    target_node: vy_ast.VyperNode, search_node: vy_ast.VyperNode
) -> Optional[vy_ast.VyperNode]:
    similar_nodes = [
        n
        for n in search_node.get_descendants(type(target_node))
        if vy_ast.compare_nodes(target_node, n)
    ]

    for node in similar_nodes:
        # raise if the node is the target of an assignment statement
        assign_node = node.get_ancestor((vy_ast.Assign, vy_ast.AugAssign))
        # note the use of get_descendants() blocks statements like
        # self.my_array[i] = x
        if assign_node and node in assign_node.target.get_descendants(include_self=True):
            return node

        attr_node = node.get_ancestor(vy_ast.Attribute)
        # note the use of get_descendants() blocks statements like
        # self.my_array[i].append(x)
        if (
            attr_node is not None
            and node in attr_node.value.get_descendants(include_self=True)
            and attr_node.attr in ("append", "pop", "extend")
        ):
            return node

    return None


# helpers
def _validate_address_code(node: vy_ast.Attribute, value_type: VyperType) -> None:
    if isinstance(value_type, AddressT) and node.attr == "code":
        # Validate `slice(<address>.code, start, length)` where `length` is constant
        parent = node.get_ancestor()
        if isinstance(parent, vy_ast.Call):
            ok_func = isinstance(parent.func, vy_ast.Name) and parent.func.id == "slice"
            ok_args = len(parent.args) == 3 and isinstance(parent.args[2], vy_ast.Int)
            if ok_func and ok_args:
                return

        raise StructureException(
            "(address).code is only allowed inside of a slice function with a constant length", node
        )


def _validate_msg_data_attribute(node: vy_ast.Attribute) -> None:
    if isinstance(node.value, vy_ast.Name) and node.value.id == "msg" and node.attr == "data":
        parent = node.get_ancestor()
        allowed_builtins = ("slice", "len", "raw_call")
        if not isinstance(parent, vy_ast.Call) or parent.get("func.id") not in allowed_builtins:
            raise StructureException(
                "msg.data is only allowed inside of the slice, len or raw_call functions", node
            )
        if parent.get("func.id") == "slice":
            ok_args = len(parent.args) == 3 and isinstance(parent.args[2], vy_ast.Int)
            if not ok_args:
                raise StructureException(
                    "slice(msg.data) must use a compile-time constant for length argument", parent
                )


def _validate_msg_value_access(node: vy_ast.Attribute) -> None:
    if isinstance(node.value, vy_ast.Name) and node.attr == "value" and node.value.id == "msg":
        raise NonPayableViolation("msg.value is not allowed in non-payable functions", node)


def _validate_pure_access(node: vy_ast.Attribute, typ: VyperType) -> None:
    env_vars = set(CONSTANT_ENVIRONMENT_VARS.keys()) | set(MUTABLE_ENVIRONMENT_VARS.keys())
    if isinstance(node.value, vy_ast.Name) and node.value.id in env_vars:
        if isinstance(typ, ContractFunctionT) and typ.mutability == StateMutability.PURE:
            return

        raise StateAccessViolation(
            "not allowed to query contract or environment variables in pure functions", node
        )


def _validate_self_reference(node: vy_ast.Name) -> None:
    # CMC 2023-10-19 this detector seems sus, things like `a.b(self)` could slip through
    if node.id == "self" and not isinstance(node.get_ancestor(), vy_ast.Attribute):
        raise StateAccessViolation("not allowed to query self in pure functions", node)


class FunctionNodeVisitor(VyperNodeVisitorBase):
    ignored_types = (vy_ast.Pass,)
    scope_name = "function"

    def __init__(
        self, vyper_module: vy_ast.Module, fn_node: vy_ast.FunctionDef, namespace: dict
    ) -> None:
        self.vyper_module = vyper_module
        self.fn_node = fn_node
        self.namespace = namespace
        self.func = fn_node._metadata["type"]
        self.expr_visitor = ExprVisitor(self.func)

        # allow internal function params to be mutable
        location, is_immutable = (
            (DataLocation.MEMORY, False) if self.func.is_internal else (DataLocation.CALLDATA, True)
        )
        for arg in self.func.arguments:
            namespace[arg.name] = VarInfo(arg.typ, location=location, is_immutable=is_immutable)

        for node in fn_node.body:
            self.visit(node)
        if self.func.return_type:
            if not check_for_terminus(fn_node.body):
                raise FunctionDeclarationException(
                    f"Missing or unmatched return statements in function '{fn_node.name}'", fn_node
                )

        # visit default args
        assert self.func.n_keyword_args == len(fn_node.args.defaults)
        for kwarg in self.func.keyword_args:
            self.expr_visitor.visit(kwarg.default_value, kwarg.typ)

    def visit(self, node):
        super().visit(node)

    def visit_AnnAssign(self, node):
        name = node.get("target.id")
        if name is None:
            raise VariableDeclarationException("Invalid assignment", node)

        if not node.value:
            raise VariableDeclarationException(
                "Memory variables must be declared with an initial value", node
            )

        typ = type_from_annotation(node.annotation, DataLocation.MEMORY)
        validate_expected_type(node.value, typ)

        try:
            self.namespace[name] = VarInfo(typ, location=DataLocation.MEMORY)
        except VyperException as exc:
            raise exc.with_annotation(node) from None

        self.expr_visitor.visit(node.target, typ)
        self.expr_visitor.visit(node.value, typ)

    def _validate_revert_reason(self, msg_node: vy_ast.VyperNode) -> None:
        if isinstance(msg_node, vy_ast.Str):
            if not msg_node.value.strip():
                raise StructureException("Reason string cannot be empty", msg_node)
            self.expr_visitor.visit(msg_node, get_exact_type_from_node(msg_node))
        elif not (isinstance(msg_node, vy_ast.Name) and msg_node.id == "UNREACHABLE"):
            try:
                validate_expected_type(msg_node, StringT(1024))
            except TypeMismatch as e:
                raise InvalidType("revert reason must fit within String[1024]") from e
            self.expr_visitor.visit(msg_node, get_exact_type_from_node(msg_node))
        # CMC 2023-10-19 nice to have: tag UNREACHABLE nodes with a special type

    def visit_Assert(self, node):
        if node.msg:
            self._validate_revert_reason(node.msg)

        try:
            validate_expected_type(node.test, BoolT())
        except InvalidType:
            raise InvalidType("Assertion test value must be a boolean", node.test)
        self.expr_visitor.visit(node.test, BoolT())

    # repeated code for Assign and AugAssign
    def _assign_helper(self, node):
        if isinstance(node.value, vy_ast.Tuple):
            raise StructureException("Right-hand side of assignment cannot be a tuple", node.value)

        target = get_expr_info(node.target)
        if isinstance(target.typ, HashMapT):
            raise StructureException(
                "Left-hand side of assignment cannot be a HashMap without a key", node
            )

        validate_expected_type(node.value, target.typ)
        target.validate_modification(node, self.func.mutability)

        self.expr_visitor.visit(node.value, target.typ)
        self.expr_visitor.visit(node.target, target.typ)

    def visit_Assign(self, node):
        self._assign_helper(node)

    def visit_AugAssign(self, node):
        self._assign_helper(node)

    def visit_Break(self, node):
        for_node = node.get_ancestor(vy_ast.For)
        if for_node is None:
            raise StructureException("`break` must be enclosed in a `for` loop", node)

    def visit_Continue(self, node):
        # TODO: use context/state instead of ast search
        for_node = node.get_ancestor(vy_ast.For)
        if for_node is None:
            raise StructureException("`continue` must be enclosed in a `for` loop", node)

    def visit_Expr(self, node):
        if not isinstance(node.value, vy_ast.Call):
            raise StructureException("Expressions without assignment are disallowed", node)

        fn_type = get_exact_type_from_node(node.value.func)
        if is_type_t(fn_type, EventT):
            raise StructureException("To call an event you must use the `log` statement", node)

        if is_type_t(fn_type, StructT):
            raise StructureException("Struct creation without assignment is disallowed", node)

        if isinstance(fn_type, ContractFunctionT):
            if (
                fn_type.mutability > StateMutability.VIEW
                and self.func.mutability <= StateMutability.VIEW
            ):
                raise StateAccessViolation(
                    f"Cannot call a mutating function from a {self.func.mutability.value} function",
                    node,
                )

            if (
                self.func.mutability == StateMutability.PURE
                and fn_type.mutability != StateMutability.PURE
            ):
                raise StateAccessViolation(
                    "Cannot call non-pure function from a pure function", node
                )

        if isinstance(fn_type, MemberFunctionT) and fn_type.is_modifying:
            # it's a dotted function call like dynarray.pop()
            expr_info = get_expr_info(node.value.func.value)
            expr_info.validate_modification(node, self.func.mutability)

        # NOTE: fetch_call_return validates call args.
        return_value = fn_type.fetch_call_return(node.value)
        if (
            return_value
            and not isinstance(fn_type, MemberFunctionT)
            and not isinstance(fn_type, ContractFunctionT)
        ):
            raise StructureException(
                f"Function '{fn_type._id}' cannot be called without assigning the result", node
            )
        self.expr_visitor.visit(node.value, fn_type)

    def visit_For(self, node):
        if isinstance(node.iter, vy_ast.Subscript):
            raise StructureException("Cannot iterate over a nested list", node.iter)

        if isinstance(node.iter, vy_ast.Call):
            # iteration via range()
            if node.iter.get("func.id") != "range":
                raise IteratorException(
                    "Cannot iterate over the result of a function call", node.iter
                )
            range_ = node.iter
            validate_call_args(range_, (1, 2), kwargs=["bound"])

            args = range_.args
            kwargs = {s.arg: s.value for s in range_.keywords or []}
            if len(args) == 1:
                # range(CONSTANT)
                n = args[0]
                bound = kwargs.pop("bound", None)
                validate_expected_type(n, IntegerT.any())

                if bound is None:
                    n_val = n._metadata.get("folded_value")
                    if not isinstance(n_val, int):
                        raise StateAccessViolation("Value must be a literal integer", n)
                    if n_val <= 0:
                        raise StructureException("For loop must have at least 1 iteration", args[0])
                    type_list = get_possible_types_from_node(n)

                else:
                    bound_val = bound._metadata.get("folded_value")
                    if bound_val is None:
                        raise StateAccessViolation("bound must be a literal", bound)
                    if bound_val <= 0:
                        raise StructureException("bound must be at least 1", args[0])
                    type_list = get_common_types(n, bound)

            else:
                if range_.keywords:
                    raise StructureException(
                        "Keyword arguments are not supported for `range(N, M)` and"
                        "`range(x, x + N)` expressions",
                        range_.keywords[0],
                    )

                validate_expected_type(args[0], IntegerT.any())
                type_list = get_common_types(*args)
                arg0_val = args[0]._metadata.get("folded_value")
                if not isinstance(arg0_val, int):
                    # range(x, x + CONSTANT)
                    if not isinstance(args[1], vy_ast.BinOp) or not isinstance(
                        args[1].op, vy_ast.Add
                    ):
                        raise StructureException(
                            "Second element must be the first element plus a literal value", args[1]
                        )
                    if not vy_ast.compare_nodes(args[0], args[1].left):
                        raise StructureException(
                            "First and second variable must be the same", args[1].left
                        )

                    right_val = args[1].right._metadata.get("folded_value")
                    if not isinstance(right_val, int):
                        raise InvalidLiteral("Literal must be an integer", args[1].right)
                    if right_val < 1:
                        raise StructureException(
                            f"For loop has invalid number of iterations ({right_val}),"
                            " the value must be greater than zero",
                            args[1].right,
                        )
                else:
                    # range(CONSTANT, CONSTANT)
                    arg1_val = args[1]._metadata.get("folded_value")
                    if not isinstance(arg1_val, int):
                        raise InvalidType("Value must be a literal integer", args[1])
                    validate_expected_type(args[1], IntegerT.any())
                    if arg0_val >= arg1_val:
                        raise StructureException("Second value must be > first value", args[1])

                if not type_list:
                    raise TypeMismatch("Iterator values are of different types", node.iter)

        else:
            # iteration over a variable or literal list
            iter_ = node.iter._metadata.get("folded_value")
            if isinstance(iter_, list) and len(iter_) == 0:
                raise StructureException("For loop must have at least 1 iteration", node.iter)

            type_list = [
                i.value_type
                for i in get_possible_types_from_node(node.iter)
                if isinstance(i, (DArrayT, SArrayT))
            ]

        if not type_list:
            raise InvalidType("Not an iterable type", node.iter)

        if isinstance(node.iter, (vy_ast.Name, vy_ast.Attribute)):
            # check for references to the iterated value within the body of the loop
            assign = _check_iterator_modification(node.iter, node)
            if assign:
                raise ImmutableViolation("Cannot modify array during iteration", assign)

        # Check if `iter` is a storage variable. get_descendants` is used to check for
        # nested `self` (e.g. structs)
        iter_is_storage_var = (
            isinstance(node.iter, vy_ast.Attribute)
            and len(node.iter.get_descendants(vy_ast.Name, {"id": "self"})) > 0
        )

        if iter_is_storage_var:
            # check if iterated value may be modified by function calls inside the loop
            iter_name = node.iter.attr
            for call_node in node.get_descendants(vy_ast.Call, {"func.value.id": "self"}):
                fn_name = call_node.func.attr

                fn_node = self.vyper_module.get_children(vy_ast.FunctionDef, {"name": fn_name})[0]
                if _check_iterator_modification(node.iter, fn_node):
                    # check for direct modification
                    raise ImmutableViolation(
                        f"Cannot call '{fn_name}' inside for loop, it potentially "
                        f"modifies iterated storage variable '{iter_name}'",
                        call_node,
                    )

                for name in self.namespace["self"].typ.members[fn_name].recursive_calls:
                    # check for indirect modification
                    fn_node = self.vyper_module.get_children(vy_ast.FunctionDef, {"name": name})[0]
                    if _check_iterator_modification(node.iter, fn_node):
                        raise ImmutableViolation(
                            f"Cannot call '{fn_name}' inside for loop, it may call to '{name}' "
                            f"which potentially modifies iterated storage variable '{iter_name}'",
                            call_node,
                        )

        if not isinstance(node.target, vy_ast.Name):
            raise StructureException("Invalid syntax for loop iterator", node.target)

        for_loop_exceptions = []
        iter_name = node.target.id
        for possible_target_type in type_list:
            # type check the for loop body using each possible type for iterator value

            with self.namespace.enter_scope():
                try:
                    self.namespace[iter_name] = VarInfo(possible_target_type, is_constant=True)
                except VyperException as exc:
                    raise exc.with_annotation(node) from None

                try:
                    with NodeMetadata.enter_typechecker_speculation():
                        for n in node.body:
                            self.visit(n)
                except (TypeMismatch, InvalidOperation) as exc:
                    for_loop_exceptions.append(exc)
                else:
                    self.expr_visitor.visit(node.target, possible_target_type)

                    if isinstance(node.iter, (vy_ast.Name, vy_ast.Attribute)):
                        iter_type = get_exact_type_from_node(node.iter)
                        # note CMC 2023-10-23: slightly redundant with how type_list is computed
                        validate_expected_type(node.target, iter_type.value_type)
                        self.expr_visitor.visit(node.iter, iter_type)
                    if isinstance(node.iter, vy_ast.List):
                        len_ = len(node.iter.elements)
                        self.expr_visitor.visit(node.iter, SArrayT(possible_target_type, len_))
                    if isinstance(node.iter, vy_ast.Call) and node.iter.func.id == "range":
                        for a in node.iter.args:
                            self.expr_visitor.visit(a, possible_target_type)
                        for a in node.iter.keywords:
                            if a.arg == "bound":
                                self.expr_visitor.visit(a.value, possible_target_type)

                    # success -- do not enter error handling section
                    return

        # failed to find a good type. bail out
        if len(set(str(i) for i in for_loop_exceptions)) == 1:
            # if every attempt at type checking raised the same exception
            raise for_loop_exceptions[0]

        # return an aggregate TypeMismatch that shows all possible exceptions
        # depending on which type is used
        types_str = [str(i) for i in type_list]
        given_str = f"{', '.join(types_str[:1])} or {types_str[-1]}"
        raise TypeMismatch(
            f"Iterator value '{iter_name}' may be cast as {given_str}, "
            "but type checking fails with all possible types:",
            node,
            *(
                (f"Casting '{iter_name}' as {typ}: {exc.message}", exc.annotations[0])
                for typ, exc in zip(type_list, for_loop_exceptions)
            ),
        )

    def visit_If(self, node):
        validate_expected_type(node.test, BoolT())
        self.expr_visitor.visit(node.test, BoolT())
        with self.namespace.enter_scope():
            for n in node.body:
                self.visit(n)
        with self.namespace.enter_scope():
            for n in node.orelse:
                self.visit(n)

    def visit_Log(self, node):
        if not isinstance(node.value, vy_ast.Call):
            raise StructureException("Log must call an event", node)
        f = get_exact_type_from_node(node.value.func)
        if not is_type_t(f, EventT):
            raise StructureException("Value is not an event", node.value)
        if self.func.mutability <= StateMutability.VIEW:
            raise StructureException(
                f"Cannot emit logs from {self.func.mutability.value.lower()} functions", node
            )
        f.fetch_call_return(node.value)
        node._metadata["type"] = f.typedef
        self.expr_visitor.visit(node.value, f.typedef)

    def visit_Raise(self, node):
        if node.exc:
            self._validate_revert_reason(node.exc)

    def visit_Return(self, node):
        values = node.value
        if values is None:
            if self.func.return_type:
                raise FunctionDeclarationException("Return statement is missing a value", node)
            return
        elif self.func.return_type is None:
            raise FunctionDeclarationException("Function does not return any values", node)

        if isinstance(values, vy_ast.Tuple):
            values = values.elements
            if not isinstance(self.func.return_type, TupleT):
                raise FunctionDeclarationException("Function only returns a single value", node)
            if self.func.return_type.length != len(values):
                raise FunctionDeclarationException(
                    f"Incorrect number of return values: "
                    f"expected {self.func.return_type.length}, got {len(values)}",
                    node,
                )
            for given, expected in zip(values, self.func.return_type.member_types):
                validate_expected_type(given, expected)
        else:
            validate_expected_type(values, self.func.return_type)
        self.expr_visitor.visit(node.value, self.func.return_type)


class ExprVisitor(VyperNodeVisitorBase):
    scope_name = "function"

    def __init__(self, fn_node: Optional[ContractFunctionT] = None):
        self.func = fn_node

    def visit(self, node, typ):
        # recurse and typecheck in case we are being fed the wrong type for
        # some reason. note that `validate_expected_type` is unnecessary
        # for nodes that already call `get_exact_type_from_node` and
        # `get_possible_types_from_node` because `validate_expected_type`
        # would be calling the same function again.
        # CMC 2023-06-27 would be cleanest to call validate_expected_type()
        # before recursing but maybe needs some refactoring before that
        # can happen.
        super().visit(node, typ)

        # annotate
        node._metadata["type"] = typ

    def visit_Attribute(self, node: vy_ast.Attribute, typ: VyperType) -> None:
        _validate_msg_data_attribute(node)

        # CMC 2023-10-19 TODO generalize this to mutability check on every node.
        # something like,
        # if self.func.mutability < expr_info.mutability:
        #    raise ...

        if self.func and self.func.mutability != StateMutability.PAYABLE:
            _validate_msg_value_access(node)

        if self.func and self.func.mutability == StateMutability.PURE:
            _validate_pure_access(node, typ)

        value_type = get_exact_type_from_node(node.value)
        _validate_address_code(node, value_type)

        self.visit(node.value, value_type)

    def visit_BinOp(self, node: vy_ast.BinOp, typ: VyperType) -> None:
        validate_expected_type(node.left, typ)
        self.visit(node.left, typ)

        rtyp = typ
        if isinstance(node.op, (vy_ast.LShift, vy_ast.RShift)):
            rtyp = get_possible_types_from_node(node.right).pop()

        validate_expected_type(node.right, rtyp)

        self.visit(node.right, rtyp)

    def visit_BoolOp(self, node: vy_ast.BoolOp, typ: VyperType) -> None:
        assert typ == BoolT()  # sanity check
        for value in node.values:
            validate_expected_type(value, BoolT())
            self.visit(value, BoolT())

    def visit_Call(self, node: vy_ast.Call, typ: VyperType) -> None:
        call_type = get_exact_type_from_node(node.func)
        # except for builtin functions, `get_exact_type_from_node`
        # already calls `validate_expected_type` on the call args
        # and kwargs via `call_type.fetch_call_return`
        self.visit(node.func, call_type)

        if isinstance(call_type, ContractFunctionT):
            # function calls
            if call_type.is_internal:
                assert self.func is not None  # make mypy happy
                self.func.called_functions.add(call_type)
            for arg, typ in zip(node.args, call_type.argument_types):
                self.visit(arg, typ)
            for kwarg in node.keywords:
                # We should only see special kwargs
                typ = call_type.call_site_kwargs[kwarg.arg].typ
                self.visit(kwarg.value, typ)

        elif is_type_t(call_type, EventT):
            # events have no kwargs
            expected_types = call_type.typedef.arguments.values()
            for arg, typ in zip(node.args, expected_types):
                self.visit(arg, typ)
        elif is_type_t(call_type, StructT):
            # struct ctors
            # ctors have no kwargs
            expected_types = call_type.typedef.members.values()
            for value, arg_type in zip(node.args[0].values, expected_types):
                self.visit(value, arg_type)
        elif isinstance(call_type, MemberFunctionT):
            assert len(node.args) == len(call_type.arg_types)
            for arg, arg_type in zip(node.args, call_type.arg_types):
                self.visit(arg, arg_type)
        else:
            # Skip annotation of builtin functions that are always folded
            # because the folded node will be annotated during folding.
            if getattr(call_type, "_is_folded", False):
                return

            # builtin functions
            arg_types = call_type.infer_arg_types(node, typ)
            # `infer_arg_types` already calls `validate_expected_type`
            for arg, arg_type in zip(node.args, arg_types):
                self.visit(arg, arg_type)
            kwarg_types = call_type.infer_kwarg_types(node)
            for kwarg in node.keywords:
                self.visit(kwarg.value, kwarg_types[kwarg.arg])

    def visit_Compare(self, node: vy_ast.Compare, typ: VyperType) -> None:
        if isinstance(node.op, (vy_ast.In, vy_ast.NotIn)):
            # membership in list literal - `x in [a, b, c]`
            # needle: ltyp, haystack: rtyp
            if isinstance(node.right, vy_ast.List):
                ltyp = get_common_types(node.left, *node.right.elements).pop()

                rlen = len(node.right.elements)
                rtyp = SArrayT(ltyp, rlen)
                validate_expected_type(node.right, rtyp)
            else:
                rtyp = get_exact_type_from_node(node.right)
                if isinstance(rtyp, EnumT):
                    # enum membership - `some_enum in other_enum`
                    ltyp = rtyp
                else:
                    # array membership - `x in my_list_variable`
                    assert isinstance(rtyp, (SArrayT, DArrayT))
                    ltyp = rtyp.value_type

            validate_expected_type(node.left, ltyp)

            self.visit(node.left, ltyp)
            self.visit(node.right, rtyp)

        else:
            # ex. a < b
            cmp_typ = get_common_types(node.left, node.right).pop()
            if isinstance(cmp_typ, _BytestringT):
                # for bytestrings, get_common_types automatically downcasts
                # to the smaller common type - that will annotate with the
                # wrong type, instead use get_exact_type_from_node (which
                # resolves to the right type for bytestrings anyways).
                ltyp = get_exact_type_from_node(node.left)
                rtyp = get_exact_type_from_node(node.right)
            else:
                ltyp = rtyp = cmp_typ
                validate_expected_type(node.left, ltyp)
                validate_expected_type(node.right, rtyp)

            self.visit(node.left, ltyp)
            self.visit(node.right, rtyp)

    def visit_Constant(self, node: vy_ast.Constant, typ: VyperType) -> None:
        validate_expected_type(node, typ)

    def visit_Index(self, node: vy_ast.Index, typ: VyperType) -> None:
        validate_expected_type(node.value, typ)
        self.visit(node.value, typ)

    def visit_List(self, node: vy_ast.List, typ: VyperType) -> None:
        assert isinstance(typ, (SArrayT, DArrayT))
        for element in node.elements:
            validate_expected_type(element, typ.value_type)
            self.visit(element, typ.value_type)

    def visit_Name(self, node: vy_ast.Name, typ: VyperType) -> None:
        if self.func is not None and self.func.mutability == StateMutability.PURE:
            _validate_self_reference(node)

        if not isinstance(typ, TYPE_T):
            validate_expected_type(node, typ)

    def visit_Subscript(self, node: vy_ast.Subscript, typ: VyperType) -> None:
        if isinstance(typ, TYPE_T):
            # don't recurse; can't annotate AST children of type definition
            return

        if isinstance(node.value, (vy_ast.List, vy_ast.Subscript)):
            possible_base_types = get_possible_types_from_node(node.value)

            for possible_type in possible_base_types:
                if typ.compare_type(possible_type.value_type):
                    base_type = possible_type
                    break
            else:
                # this should have been caught in
                # `get_possible_types_from_node` but wasn't.
                raise TypeCheckFailure(f"Expected {typ} but it is not a possible type", node)

        else:
            base_type = get_exact_type_from_node(node.value)

        # get the correct type for the index, it might
        # not be exactly base_type.key_type
        # note: index_type is validated in types_from_Subscript
        index_types = get_possible_types_from_node(node.slice.value)
        index_type = index_types.pop()

        self.visit(node.slice, index_type)
        self.visit(node.value, base_type)

    def visit_Tuple(self, node: vy_ast.Tuple, typ: VyperType) -> None:
        if isinstance(typ, TYPE_T):
            # don't recurse; can't annotate AST children of type definition
            return

        assert isinstance(typ, TupleT)
        for element, subtype in zip(node.elements, typ.member_types):
            validate_expected_type(element, subtype)
            self.visit(element, subtype)

    def visit_UnaryOp(self, node: vy_ast.UnaryOp, typ: VyperType) -> None:
        validate_expected_type(node.operand, typ)
        self.visit(node.operand, typ)

    def visit_IfExp(self, node: vy_ast.IfExp, typ: VyperType) -> None:
        validate_expected_type(node.test, BoolT())
        self.visit(node.test, BoolT())
        validate_expected_type(node.body, typ)
        self.visit(node.body, typ)
        validate_expected_type(node.orelse, typ)
        self.visit(node.orelse, typ)

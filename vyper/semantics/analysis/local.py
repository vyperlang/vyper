# CMC 2024-02-03 TODO: split me into function.py and expr.py

from typing import Optional

from vyper import ast as vy_ast
from vyper.ast.validation import validate_call_args
from vyper.exceptions import (
    CallViolation,
    ExceptionList,
    FunctionDeclarationException,
    ImmutableViolation,
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
from vyper.semantics.analysis.base import Modifiability, ModuleOwnership, VarInfo
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
    VOID_TYPE,
    AddressT,
    BoolT,
    DArrayT,
    EventT,
    FlagT,
    HashMapT,
    SArrayT,
    StringT,
    StructT,
    TupleT,
    VyperType,
    _BytestringT,
    is_type_t,
    map_void,
)
from vyper.semantics.types.function import ContractFunctionT, MemberFunctionT, StateMutability
from vyper.semantics.types.utils import type_from_annotation


def validate_functions(vy_module: vy_ast.Module) -> None:
    """Analyzes a vyper ast and validates the function bodies"""
    err_list = ExceptionList()
    namespace = get_namespace()
    for node in vy_module.get_children(vy_ast.FunctionDef):
        with namespace.enter_scope():
            try:
                analyzer = FunctionAnalyzer(vy_module, node, namespace)
                analyzer.analyze()
            except VyperException as e:
                err_list.append(e)

    err_list.raise_if_not_empty()


# finds the terminus node for a list of nodes.
# raises an exception if any nodes are unreachable
def find_terminating_node(node_list: list) -> Optional[vy_ast.VyperNode]:
    ret = None

    for node in node_list:
        if ret is not None:
            raise StructureException("Unreachable code!", node)

        if node.is_terminus:
            ret = node

        if isinstance(node, vy_ast.If):
            body_terminates = find_terminating_node(node.body)

            else_terminates = None
            if node.orelse is not None:
                else_terminates = find_terminating_node(node.orelse)

            if body_terminates is not None and else_terminates is not None:
                ret = else_terminates

        if isinstance(node, vy_ast.For):
            # call find_terminating_node for its side effects
            find_terminating_node(node.body)

    return ret


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


class FunctionAnalyzer(VyperNodeVisitorBase):
    ignored_types = (vy_ast.Pass,)
    scope_name = "function"

    def __init__(
        self, vyper_module: vy_ast.Module, fn_node: vy_ast.FunctionDef, namespace: dict
    ) -> None:
        self.vyper_module = vyper_module
        self.fn_node = fn_node
        self.namespace = namespace
        self.func = fn_node._metadata["func_type"]
        self.expr_visitor = ExprVisitor(self)

    def analyze(self):
        # allow internal function params to be mutable
        if self.func.is_internal:
            location, modifiability = (DataLocation.MEMORY, Modifiability.MODIFIABLE)
        else:
            location, modifiability = (DataLocation.CALLDATA, Modifiability.RUNTIME_CONSTANT)

        for arg in self.func.arguments:
            self.namespace[arg.name] = VarInfo(
                arg.typ, location=location, modifiability=modifiability
            )

        for node in self.fn_node.body:
            self.visit(node)

        if self.func.return_type:
            if not find_terminating_node(self.fn_node.body):
                raise FunctionDeclarationException(
                    f"Missing return statement in function '{self.fn_node.name}'", self.fn_node
                )
        else:
            # call find_terminator for its unreachable code detection side effect
            find_terminating_node(self.fn_node.body)

        # visit default args
        assert self.func.n_keyword_args == len(self.fn_node.args.defaults)
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

        # validate the value before adding it to the namespace
        self.expr_visitor.visit(node.value, typ)

        self.namespace[name] = VarInfo(typ, location=DataLocation.MEMORY)

        self.expr_visitor.visit(node.target, typ)

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

        self.expr_visitor.visit(node.test, BoolT())

    # repeated code for Assign and AugAssign
    def _assign_helper(self, node):
        if isinstance(node.value, vy_ast.Tuple):
            raise StructureException("Right-hand side of assignment cannot be a tuple", node.value)

        target = get_expr_info(node.target)

        # check mutability of the function
        self._handle_modification(node.target)

        self.expr_visitor.visit(node.value, target.typ)
        self.expr_visitor.visit(node.target, target.typ)

    def _handle_modification(self, target: vy_ast.ExprNode):
        if isinstance(target, vy_ast.Tuple):
            for item in target.elements:
                self._handle_modification(item)
            return

        # check a modification of `target`. validate the modification is
        # valid, and log the modification in relevant data structures.
        func_t = self.func
        info = get_expr_info(target)

        if isinstance(info.typ, HashMapT):
            raise StructureException(
                "Left-hand side of assignment cannot be a HashMap without a key"
            )

        if (
            info.location in (DataLocation.STORAGE, DataLocation.TRANSIENT)
            and func_t.mutability <= StateMutability.VIEW
        ):
            raise StateAccessViolation(
                f"Cannot modify {info.location} variable in a {func_t.mutability} function"
            )

        if info.location == DataLocation.CALLDATA:
            raise ImmutableViolation("Cannot write to calldata")

        if info.modifiability == Modifiability.RUNTIME_CONSTANT:
            if info.location == DataLocation.CODE:
                if not func_t.is_constructor:
                    raise ImmutableViolation("Immutable value cannot be written to")

                # handle immutables
                if info.var_info is not None:  # don't handle complex (struct,array) immutables
                    # special handling for immutable variables in the ctor
                    # TODO: maybe we want to remove this restriction.
                    if info.var_info._modification_count != 0:
                        raise ImmutableViolation(
                            "Immutable value cannot be modified after assignment"
                        )
                    info.var_info._modification_count += 1
            else:
                raise ImmutableViolation("Environment variable cannot be written to")

        if info.modifiability == Modifiability.CONSTANT:
            raise ImmutableViolation("Constant value cannot be written to.")

        var_info = info.get_root_varinfo()
        assert var_info is not None

        info._writes.add(var_info)

    def _check_module_use(self, target: vy_ast.ExprNode):
        module_infos = []
        for t in get_expr_info(target).attribute_chain:
            if t.module_info is not None:
                module_infos.append(t.module_info)

        if len(module_infos) == 0:
            return

        for module_info in module_infos:
            if module_info.ownership < ModuleOwnership.USES:
                msg = f"Cannot access `{module_info.alias}` state!"
                hint = f"add `uses: {module_info.alias}` or "
                hint += f"`initializes: {module_info.alias}` as "
                hint += "a top-level statement to your contract"
                raise ImmutableViolation(msg, hint=hint)

        # the leftmost- referenced module
        root_module_info = module_infos[0]

        # log the access
        self.func._used_modules.add(root_module_info)

    def visit_Assign(self, node):
        self._assign_helper(node)

    def visit_AugAssign(self, node):
        self._assign_helper(node)
        node.target._expr_info.typ.validate_numeric_op(node)

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
        if isinstance(node.value, vy_ast.Ellipsis):
            raise StructureException(
                "`...` is not allowed in `.vy` files! "
                "Did you mean to import me as a `.vyi` file?",
                node,
            )

        if not isinstance(node.value, vy_ast.Call):
            raise StructureException("Expressions without assignment are disallowed", node)

        fn_type = get_exact_type_from_node(node.value.func)

        if is_type_t(fn_type, EventT):
            raise StructureException("To call an event you must use the `log` statement", node)

        if is_type_t(fn_type, StructT):
            raise StructureException("Struct creation without assignment is disallowed", node)

        # NOTE: fetch_call_return validates call args.
        return_value = map_void(fn_type.fetch_call_return(node.value))
        if (
            return_value is not VOID_TYPE
            and not isinstance(fn_type, MemberFunctionT)
            and not isinstance(fn_type, ContractFunctionT)
        ):
            raise StructureException(
                f"Function '{fn_type._id}' cannot be called without assigning the result", node
            )
        self.expr_visitor.visit(node.value, return_value)

    def visit_For(self, node):
        if not isinstance(node.target.target, vy_ast.Name):
            raise StructureException("Invalid syntax for loop iterator", node.target.target)

        target_type = type_from_annotation(node.target.annotation, DataLocation.MEMORY)

        if isinstance(node.iter, vy_ast.Call):
            # iteration via range()
            if node.iter.get("func.id") != "range":
                raise IteratorException(
                    "Cannot iterate over the result of a function call", node.iter
                )
            _validate_range_call(node.iter)

        else:
            # iteration over a variable or literal list
            iter_val = node.iter.get_folded_value() if node.iter.has_folded_value else node.iter
            if isinstance(iter_val, vy_ast.List) and len(iter_val.elements) == 0:
                raise StructureException("For loop must have at least 1 iteration", node.iter)

            if not any(
                isinstance(i, (DArrayT, SArrayT)) for i in get_possible_types_from_node(node.iter)
            ):
                raise InvalidType("Not an iterable type", node.iter)

        if isinstance(node.iter, (vy_ast.Name, vy_ast.Attribute)):
            # check for references to the iterated value within the body of the loop
            assign = _check_iterator_modification(node.iter, node)
            if assign:
                raise ImmutableViolation("Cannot modify array during iteration", assign)

        # Check if `iter` is a storage variable. get_descendants` is used to check for
        # nested `self` (e.g. structs)
        # NOTE: this analysis will be borked once stateful modules are allowed!
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

                for reachable_t in (
                    self.namespace["self"].typ.members[fn_name].reachable_internal_functions
                ):
                    # check for indirect modification
                    name = reachable_t.name
                    fn_node = self.vyper_module.get_children(vy_ast.FunctionDef, {"name": name})[0]
                    if _check_iterator_modification(node.iter, fn_node):
                        raise ImmutableViolation(
                            f"Cannot call '{fn_name}' inside for loop, it may call to '{name}' "
                            f"which potentially modifies iterated storage variable '{iter_name}'",
                            call_node,
                        )

        target_name = node.target.target.id
        with self.namespace.enter_scope():
            self.namespace[target_name] = VarInfo(
                target_type, modifiability=Modifiability.RUNTIME_CONSTANT
            )

            for stmt in node.body:
                self.visit(stmt)

            self.expr_visitor.visit(node.target.target, target_type)

            if isinstance(node.iter, vy_ast.List):
                len_ = len(node.iter.elements)
                self.expr_visitor.visit(node.iter, SArrayT(target_type, len_))
            elif isinstance(node.iter, vy_ast.Call) and node.iter.func.id == "range":
                args = node.iter.args
                kwargs = [s.value for s in node.iter.keywords]
                for arg in (*args, *kwargs):
                    self.expr_visitor.visit(arg, target_type)
            else:
                iter_type = get_exact_type_from_node(node.iter)
                self.expr_visitor.visit(node.iter, iter_type)

    def visit_If(self, node):
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
        t = map_void(f.fetch_call_return(node.value))
        # CMC 2024-02-05 annotate the event type for codegen usage
        # TODO: refactor this
        node._metadata["type"] = f.typedef
        self.expr_visitor.visit(node.value, t)

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
            raise FunctionDeclarationException("Function should not return any values", node)

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

        self.expr_visitor.visit(node.value, self.func.return_type)


class ExprVisitor(VyperNodeVisitorBase):
    def __init__(self, function_analyzer: Optional[FunctionAnalyzer] = None):
        self.function_analyzer = function_analyzer

    @property
    def func(self):
        if self.function_analyzer is None:
            return None
        return self.function_analyzer.func

    @property
    def scope_name(self):
        if self.func is not None:
            return "function"
        return "module"

    def visit(self, node, typ):
        if typ is not VOID_TYPE and not isinstance(typ, TYPE_T):
            validate_expected_type(node, typ)

        # recurse and typecheck in case we are being fed the wrong type for
        # some reason.
        super().visit(node, typ)

        # annotate
        node._metadata["type"] = typ

        if not isinstance(typ, TYPE_T):
            info = get_expr_info(node)  # get_expr_info fills in node._expr_info

            # log variable accesses.
            # (note writes will get logged as both read+write)
            varinfo = info.var_info
            if varinfo is not None:
                info._reads.add(varinfo)

            if self.func:
                variable_accesses = info._writes | info._reads
                for s in variable_accesses:
                    if s.is_module_variable():
                        self.function_analyzer._check_module_use(node)

                self.func._variable_writes.update(info._writes)
                self.func._variable_reads.update(info._reads)

        # validate and annotate folded value
        if node.has_folded_value:
            folded_node = node.get_folded_value()
            self.visit(folded_node, typ)

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
        self.visit(node.left, typ)

        rtyp = typ
        if isinstance(node.op, (vy_ast.LShift, vy_ast.RShift)):
            rtyp = get_possible_types_from_node(node.right).pop()

        self.visit(node.right, rtyp)

    def visit_BoolOp(self, node: vy_ast.BoolOp, typ: VyperType) -> None:
        assert typ == BoolT()  # sanity check
        for value in node.values:
            self.visit(value, BoolT())

    def _check_call_mutability(self, call_mutability: StateMutability):
        # note: payable can be called from nonpayable functions
        ok = (
            call_mutability <= self.func.mutability
            or self.func.mutability >= StateMutability.NONPAYABLE
        )
        if not ok:
            msg = f"Cannot call a {call_mutability} function from a {self.func.mutability} function"
            raise StateAccessViolation(msg)

    def visit_Call(self, node: vy_ast.Call, typ: VyperType) -> None:
        func_info = get_expr_info(node.func, is_callable=True)
        func_type = func_info.typ
        self.visit(node.func, func_type)

        if isinstance(func_type, ContractFunctionT):
            # function calls

            func_info._writes.update(func_type._variable_writes)
            func_info._reads.update(func_type._variable_reads)

            if self.function_analyzer:
                if func_type.is_internal:
                    self.func.called_functions.add(func_type)

                self._check_call_mutability(func_type.mutability)

                # check that if the function accesses state, the defining
                # module has been `used` or `initialized`.
                for s in func_type._variable_accesses:
                    if s.is_module_variable():
                        self.function_analyzer._check_module_use(node.func)

                if func_type.is_deploy and not self.func.is_deploy:
                    raise CallViolation(
                        f"Cannot call an @{func_type.visibility} function from "
                        f"an @{self.func.visibility} function!",
                        node,
                    )

            for arg, typ in zip(node.args, func_type.argument_types):
                self.visit(arg, typ)
            for kwarg in node.keywords:
                # We should only see special kwargs
                typ = func_type.call_site_kwargs[kwarg.arg].typ
                self.visit(kwarg.value, typ)

        elif is_type_t(func_type, EventT):
            # events have no kwargs
            expected_types = func_type.typedef.arguments.values()  # type: ignore
            for arg, typ in zip(node.args, expected_types):
                self.visit(arg, typ)
        elif is_type_t(func_type, StructT):
            # struct ctors
            # ctors have no kwargs
            expected_types = func_type.typedef.members.values()  # type: ignore
            for value, arg_type in zip(node.args[0].values, expected_types):
                self.visit(value, arg_type)
        elif isinstance(func_type, MemberFunctionT):
            if func_type.is_modifying and self.function_analyzer is not None:
                # TODO refactor this
                self.function_analyzer._handle_modification(node.func)
            assert len(node.args) == len(func_type.arg_types)
            for arg, arg_type in zip(node.args, func_type.arg_types):
                self.visit(arg, arg_type)
        else:
            # builtin functions
            arg_types = func_type.infer_arg_types(node, expected_return_typ=typ)  # type: ignore
            for arg, arg_type in zip(node.args, arg_types):
                self.visit(arg, arg_type)
            kwarg_types = func_type.infer_kwarg_types(node)  # type: ignore
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
            else:
                rtyp = get_exact_type_from_node(node.right)
                if isinstance(rtyp, FlagT):
                    # enum membership - `some_enum in other_enum`
                    ltyp = rtyp
                else:
                    # array membership - `x in my_list_variable`
                    assert isinstance(rtyp, (SArrayT, DArrayT))
                    ltyp = rtyp.value_type

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

            self.visit(node.left, ltyp)
            self.visit(node.right, rtyp)

    def visit_Constant(self, node: vy_ast.Constant, typ: VyperType) -> None:
        pass

    def visit_IfExp(self, node: vy_ast.IfExp, typ: VyperType) -> None:
        self.visit(node.test, BoolT())
        self.visit(node.body, typ)
        self.visit(node.orelse, typ)

    def visit_List(self, node: vy_ast.List, typ: VyperType) -> None:
        assert isinstance(typ, (SArrayT, DArrayT))
        for element in node.elements:
            self.visit(element, typ.value_type)

    def visit_Name(self, node: vy_ast.Name, typ: VyperType) -> None:
        if self.func:
            # TODO: refactor to use expr_info mutability
            if self.func.mutability == StateMutability.PURE:
                _validate_self_reference(node)

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
        index_types = get_possible_types_from_node(node.slice)
        index_type = index_types.pop()

        self.visit(node.slice, index_type)
        self.visit(node.value, base_type)

    def visit_Tuple(self, node: vy_ast.Tuple, typ: VyperType) -> None:
        if isinstance(typ, TYPE_T):
            # don't recurse; can't annotate AST children of type definition
            return

        # these guarantees should be provided by validate_expected_type
        assert isinstance(typ, TupleT)
        assert len(node.elements) == len(typ.member_types)

        for item_ast, item_type in zip(node.elements, typ.member_types):
            self.visit(item_ast, item_type)

    def visit_UnaryOp(self, node: vy_ast.UnaryOp, typ: VyperType) -> None:
        self.visit(node.operand, typ)


def _validate_range_call(node: vy_ast.Call):
    """
    Check that the arguments to a range() call are valid.
    :param node: call to range()
    :return: None
    """
    assert node.func.get("id") == "range"
    validate_call_args(node, (1, 2), kwargs=["bound"])
    kwargs = {s.arg: s.value for s in node.keywords or []}
    start, end = (vy_ast.Int(value=0), node.args[0]) if len(node.args) == 1 else node.args
    start, end = [i.get_folded_value() if i.has_folded_value else i for i in (start, end)]

    if "bound" in kwargs:
        bound = kwargs["bound"]
        if bound.has_folded_value:
            bound = bound.get_folded_value()
        if not isinstance(bound, vy_ast.Num):
            raise StateAccessViolation("Bound must be a literal", bound)
        if bound.value <= 0:
            raise StructureException("Bound must be at least 1", bound)
        if isinstance(start, vy_ast.Num) and isinstance(end, vy_ast.Num):
            error = "Please remove the `bound=` kwarg when using range with constants"
            raise StructureException(error, bound)
    else:
        for arg in (start, end):
            if not isinstance(arg, vy_ast.Num):
                error = "Value must be a literal integer, unless a bound is specified"
                raise StateAccessViolation(error, arg)
        if end.value <= start.value:
            raise StructureException("End must be greater than start", end)

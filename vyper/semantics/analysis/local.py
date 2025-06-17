# CMC 2024-02-03 TODO: rename me to function.py

import contextlib
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

# TODO consolidate some of these imports
from vyper.semantics.analysis.base import (
    Modifiability,
    ModuleInfo,
    ModuleOwnership,
    VarAccess,
    VarInfo,
)
from vyper.semantics.analysis.common import VyperNodeVisitorBase
from vyper.semantics.analysis.utils import (
    get_common_types,
    get_exact_type_from_node,
    get_expr_info,
    get_possible_types_from_node,
    uses_state,
    validate_expected_type,
)
from vyper.semantics.data_locations import DataLocation
from vyper.semantics.environment import CONSTANT_ENVIRONMENT_VARS
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
    IntegerT,
    SArrayT,
    SelfT,
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


def analyze_functions(vy_module: vy_ast.Module) -> None:
    """Analyzes a vyper ast and validates the function bodies"""
    err_list = ExceptionList()

    for node in vy_module.get_children(vy_ast.FunctionDef):
        _analyze_function_r(vy_module, node, err_list)

    for node in vy_module.get_children(vy_ast.VariableDecl):
        if not node.is_public:
            continue
        _analyze_function_r(vy_module, node._expanded_getter, err_list)

    err_list.raise_if_not_empty()


def _analyze_function_r(
    vy_module: vy_ast.Module, node: vy_ast.FunctionDef, err_list: ExceptionList
):
    func_t = node._metadata["func_type"]

    for call_t in func_t.called_functions:
        if isinstance(call_t, ContractFunctionT):
            assert isinstance(call_t.ast_def, vy_ast.FunctionDef)  # help mypy
            _analyze_function_r(vy_module, call_t.ast_def, err_list)

    namespace = get_namespace()

    try:
        with namespace.enter_scope():
            analyzer = FunctionAnalyzer(vy_module, node, namespace)
            analyzer.analyze()
    except VyperException as e:
        err_list.append(e)


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


# helpers
def _validate_address_code(node: vy_ast.Attribute, value_type: VyperType) -> None:
    if isinstance(value_type, AddressT) and node.attr == "code":
        # Validate `slice(<address>.code, start, length)` where `length` is constant
        parent = node.get_ancestor()
        if isinstance(parent, vy_ast.Call):
            ok_func = isinstance(parent.func, vy_ast.Name) and parent.func.id == "slice"
            ok_args = len(parent.args) == 3 and isinstance(parent.args[2].reduced(), vy_ast.Int)
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
            ok_args = len(parent.args) == 3 and isinstance(parent.args[2].reduced(), vy_ast.Int)
            if not ok_args:
                raise StructureException(
                    "slice(msg.data) must use a compile-time constant for length argument", parent
                )


def _validate_msg_value_access(node: vy_ast.Attribute) -> None:
    if isinstance(node.value, vy_ast.Name) and node.attr == "value" and node.value.id == "msg":
        raise NonPayableViolation("msg.value is not allowed in non-payable functions", node)


def _validate_pure_access(node: vy_ast.Attribute | vy_ast.Name, typ: VyperType) -> None:
    if isinstance(typ, TYPE_T):
        return

    info = get_expr_info(node)

    env_vars = CONSTANT_ENVIRONMENT_VARS
    # check env variable access like `block.number`
    if isinstance(node, vy_ast.Attribute):
        if node.get("value.id") in env_vars:
            raise StateAccessViolation(
                "not allowed to query environment variables in pure functions"
            )
        # allow type exprs in the value node, e.g. MyFlag.A
        parent_info = get_expr_info(node.value, is_callable=True)
        if isinstance(parent_info.typ, AddressT) and node.attr in AddressT._type_members:
            raise StateAccessViolation("not allowed to query address members in pure functions")

    if (varinfo := info.var_info) is None:
        return
    # self is magic. we only need to check it if it is not the root of an Attribute
    # node. (i.e. it is bare like `self`, not `self.foo`)
    is_naked_self = isinstance(varinfo.typ, SelfT) and not isinstance(
        node.get_ancestor(), vy_ast.Attribute
    )
    if is_naked_self:
        raise StateAccessViolation("not allowed to query `self` in pure functions")

    if varinfo.is_state_variable() or is_naked_self:
        raise StateAccessViolation("not allowed to query state variables in pure functions")


# analyse the variable access for the attribute chain for a node
# e.x. `x` will return varinfo for `x`
# `module.foo` will return VarAccess for `module.foo`
# `self.my_struct.x.y` will return VarAccess for `self.my_struct.x.y`
def _get_variable_access(node: vy_ast.ExprNode) -> Optional[VarAccess]:
    path: list[str | object] = []
    info = get_expr_info(node)

    while info.var_info is None:
        if not isinstance(node, (vy_ast.Subscript, vy_ast.Attribute)):
            # it's something like a literal
            return None

        if isinstance(node, vy_ast.Subscript):
            # Subscript is an analysis barrier
            # we cannot analyse if `x.y[ix1].z` overlaps with `x.y[ix2].z`.
            path.append(VarAccess.SUBSCRIPT_ACCESS)

        if (attr := info.attr) is not None:
            path.append(attr)

        assert isinstance(node, (vy_ast.Subscript, vy_ast.Attribute))  # help mypy
        node = node.value
        info = get_expr_info(node)

    # ignore `self.` as it interferes with VarAccess comparison across modules
    if len(path) > 0 and path[-1] == "self":
        path.pop()
    path.reverse()

    return VarAccess(info.var_info, tuple(path))


# get the chain of modules, e.g.
# mod1.mod2.x.y -> [ModuleInfo(mod1), ModuleInfo(mod2)]
# CMC 2024-02-12 note that the Attribute/Subscript traversal in this and
# _get_variable_access() are a bit gross and could probably
# be refactored into data on ExprInfo.
def _get_module_chain(node: vy_ast.ExprNode) -> list[ModuleInfo]:
    ret: list[ModuleInfo] = []
    info = get_expr_info(node)

    while True:
        if info.module_info is not None:
            ret.append(info.module_info)

        if not isinstance(node, (vy_ast.Subscript, vy_ast.Attribute)):
            break

        node = node.value
        info = get_expr_info(node)

    ret.reverse()
    return ret


def check_module_uses(node: vy_ast.ExprNode) -> Optional[ModuleInfo]:
    """
    validate module usage, and that if we use lib1.lib2.<state>, that
    lib1 at least `uses` lib2.

    Returns the left-most module referenced in the expr,
        e.g. `lib1.lib2.foo` should return module info for `lib1`.
    """
    module_infos = _get_module_chain(node)

    if len(module_infos) == 0:
        return None

    for module_info in module_infos:
        if module_info.ownership < ModuleOwnership.USES:
            msg = f"Cannot access `{module_info.alias}` state!\n  note that"
            # CMC 2024-04-12 add UX note about nonreentrant. might be nice
            # in the future to be more specific about exactly which state is
            # used, although that requires threading a bit more context into
            # this function.
            msg += " use of the `@nonreentrant` decorator is also considered"
            msg += " state access"

            hint = f"add `uses: {module_info.alias}` or "
            hint += f"`initializes: {module_info.alias}` as "
            hint += "a top-level statement to your contract"
            raise ImmutableViolation(msg, hint=hint)

    # the leftmost- referenced module
    root_module_info = module_infos[0]
    return root_module_info


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

        self.loop_variables: list[Optional[VarAccess]] = []

    def analyze(self):
        if self.func.analysed:
            return

        # mark seen before analysing, if analysis throws an exception which
        # gets caught, we don't want to analyse again.
        self.func.mark_analysed()

        # allow internal function params to be mutable
        if self.func.is_internal:
            location, modifiability = (DataLocation.MEMORY, Modifiability.MODIFIABLE)
        else:
            location, modifiability = (DataLocation.CALLDATA, Modifiability.RUNTIME_CONSTANT)

        for arg in self.func.arguments:
            self.namespace[arg.name] = VarInfo(
                arg.typ, location=location, modifiability=modifiability, decl_node=arg.ast_source
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

    @contextlib.contextmanager
    def enter_for_loop(self, varaccess: Optional[VarAccess]):
        self.loop_variables.append(varaccess)
        try:
            yield
        finally:
            self.loop_variables.pop()

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

        self.namespace[name] = VarInfo(typ, location=DataLocation.MEMORY, decl_node=node)

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

        var_access = _get_variable_access(target)
        assert var_access is not None

        info._writes.add(var_access)

    def _handle_module_access(self, target: vy_ast.ExprNode):
        root_module_info = check_module_uses(target)

        if root_module_info is not None:
            # log the access
            self.func.mark_used_module(root_module_info)

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

        # NOTE: standalone staticcalls are banned!
        if not isinstance(node.value, (vy_ast.Call, vy_ast.ExtCall)):
            raise StructureException(
                "Expressions without assignment are disallowed",
                node,
                hint="did you mean to assign the result to a variable?",
            )

        if isinstance(node.value, vy_ast.ExtCall):
            call_node = node.value.value
        else:
            call_node = node.value

        func = call_node.func

        fn_type = get_exact_type_from_node(func)

        if is_type_t(fn_type, EventT):
            raise StructureException("To call an event you must use the `log` statement", node)

        if is_type_t(fn_type, StructT):
            raise StructureException("Struct creation without assignment is disallowed", node)

        # NOTE: fetch_call_return validates call args.
        return_value = map_void(fn_type.fetch_call_return(call_node))
        if (
            return_value is not VOID_TYPE
            and not isinstance(fn_type, MemberFunctionT)
            and not isinstance(fn_type, ContractFunctionT)
        ):
            raise StructureException(
                f"Function `{fn_type}` cannot be called without assigning the result"
            )
        self.expr_visitor.visit(node.value, return_value)

    def _analyse_range_iter(self, iter_node, target_type):
        # iteration via range()
        if iter_node.get("func.id") != "range":
            # CMC 2025-02-12 I think we can allow this actually
            raise IteratorException("Cannot iterate over the result of a function call", iter_node)
        _validate_range_call(iter_node)

        args = iter_node.args
        kwargs = [s.value for s in iter_node.keywords]
        for arg in (*args, *kwargs):
            self.expr_visitor.visit(arg, target_type)

    def _analyse_list_iter(self, target_node, iter_node, target_type):
        # iteration over a variable or literal list
        iter_val = iter_node.reduced()

        if isinstance(iter_val, vy_ast.List):
            len_ = len(iter_val.elements)
            if len_ == 0:
                raise StructureException("For loop must have at least 1 iteration", iter_node)
            iter_type = SArrayT(target_type, len_)
        else:
            try:
                iter_type = get_exact_type_from_node(iter_node)

            except (InvalidType, StructureException):
                raise InvalidType("Not an iterable type", iter_node)

        # CMC 2024-02-09 TODO: use validate_expected_type once we have DArrays
        # with generic length.
        if not isinstance(iter_type, (DArrayT, SArrayT)):
            raise InvalidType("Not an iterable type", iter_node)

        if not target_type.compare_type(iter_type.value_type):
            raise TypeMismatch(f"Expected type of {iter_type.value_type}", target_node)

        self.expr_visitor.visit(iter_node, iter_type)

        # get the root varinfo from iter_val in case we need to peer
        # through folded constants
        return _get_variable_access(iter_val)

    def visit_For(self, node):
        if not isinstance(node.target.target, vy_ast.Name):
            raise StructureException("Invalid syntax for loop iterator", node.target.target)

        target_type = type_from_annotation(node.target.annotation, DataLocation.MEMORY)

        iter_var = None
        if isinstance(node.iter, vy_ast.Call):
            self._analyse_range_iter(node.iter, target_type)

            # sanity check the postcondition of analyse_range_iter
            assert isinstance(target_type, IntegerT)
        else:
            # note: using `node.target` here results in bad source location.
            iter_var = self._analyse_list_iter(node.target.target, node.iter, target_type)

        with self.namespace.enter_scope(), self.enter_for_loop(iter_var):
            target_name = node.target.target.id
            # maybe we should introduce a new Modifiability: LOOP_VARIABLE
            self.namespace[target_name] = VarInfo(
                target_type, modifiability=Modifiability.RUNTIME_CONSTANT, decl_node=node.target
            )

            self.expr_visitor.visit(node.target.target, target_type)

            for stmt in node.body:
                self.visit(stmt)

    def visit_If(self, node):
        self.expr_visitor.visit(node.test, BoolT())
        with self.namespace.enter_scope():
            for n in node.body:
                self.visit(n)
        with self.namespace.enter_scope():
            for n in node.orelse:
                self.visit(n)

    def visit_Log(self, node):
        # postcondition of Log.validate()
        assert isinstance(node.value, vy_ast.Call)

        f = get_exact_type_from_node(node.value.func)
        if not is_type_t(f, EventT):
            raise StructureException("Value is not an event", node.value)
        if self.func.mutability <= StateMutability.VIEW:
            raise StructureException(
                f"Cannot emit logs from {self.func.mutability} functions", node
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
            var_access = _get_variable_access(node)
            if var_access is not None:
                info._reads.add(var_access)

            if self.function_analyzer:
                for s in self.function_analyzer.loop_variables:
                    if s is None:
                        continue

                    for v in info._writes:
                        if not v.contains(s):
                            continue

                        msg = "Cannot modify loop variable"
                        var = s.variable
                        if var.decl_node is not None:
                            msg += f" `{var.decl_node.target.id}`"
                        raise ImmutableViolation(msg, var.decl_node, node)

                var_accesses = info._writes | info._reads
                if uses_state(var_accesses):
                    self.function_analyzer._handle_module_access(node)

                self.func.mark_variable_writes(info._writes)
                self.func.mark_variable_reads(info._reads)

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

    def visit_ExtCall(self, node, typ):
        return self.visit(node.value, typ)

    def visit_StaticCall(self, node, typ):
        return self.visit(node.value, typ)

    def visit_Call(self, node: vy_ast.Call, typ: VyperType) -> None:
        func_info = get_expr_info(node.func, is_callable=True)
        func_type = func_info.typ

        # TODO: unify the APIs for different callable types so that
        # we don't need so much branching here.

        if not node.is_plain_call and not isinstance(func_type, ContractFunctionT):
            kind = node.kind_str
            msg = f"cannot use `{kind}` here!"
            hint = f"remove the `{kind}` keyword"
            raise CallViolation(msg, node.parent, hint=hint)

        if isinstance(func_type, ContractFunctionT):
            # function calls
            if func_type.is_external:
                missing_keyword = node.is_plain_call
                is_static = func_type.mutability < StateMutability.NONPAYABLE

                if is_static != node.is_staticcall or missing_keyword:
                    should = "staticcall" if is_static else "extcall"
                    msg = f"Calls to external {func_type.mutability} functions "
                    msg += f"must use the `{should}` keyword."
                    hint = f"try `{should} {node.node_source_code}`"
                    raise CallViolation(msg, hint=hint)

                if func_type.is_fallback:
                    msg = "`__default__` function cannot be called directly."
                    msg += " If you mean to call the default function, use `raw_call`"
                    raise CallViolation(msg)
            else:
                if not node.is_plain_call:
                    kind = node.kind_str
                    msg = f"Calls to internal functions cannot use the `{kind}` keyword."
                    hint = f"remove the `{kind}` keyword"
                    raise CallViolation(msg, node.parent, hint=hint)

            if not func_type.from_interface:
                for s in func_type.get_variable_writes():
                    if s.variable.is_state_variable():
                        func_info._writes.add(s)
                for s in func_type.get_variable_reads():
                    if s.variable.is_state_variable():
                        func_info._reads.add(s)

            if self.function_analyzer:
                self._check_call_mutability(func_type.mutability)

                if func_type.uses_state():
                    self.function_analyzer._handle_module_access(node.func)

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
            # event ctors
            expected_types = func_type.typedef.arguments.values()  # type: ignore
            # Handle keyword args if present, otherwise use positional args
            if len(node.keywords) > 0:
                for kwarg, arg_type in zip(node.keywords, expected_types):
                    self.visit(kwarg.value, arg_type)
            else:
                for arg, typ in zip(node.args, expected_types):
                    self.visit(arg, typ)
        elif is_type_t(func_type, StructT):
            # struct ctors
            expected_types = func_type.typedef.members.values()  # type: ignore
            for kwarg, arg_type in zip(node.keywords, expected_types):
                self.visit(kwarg.value, arg_type)
        elif isinstance(func_type, MemberFunctionT):
            if func_type.is_modifying and self.function_analyzer is not None:
                # TODO refactor this
                assert isinstance(node.func, vy_ast.Attribute)  # help mypy
                self.function_analyzer._handle_modification(node.func.value)
            assert len(node.args) == len(func_type.arg_types)
            for arg, arg_type in zip(node.args, func_type.arg_types):
                self.visit(arg, arg_type)
        else:
            # builtin functions and interfaces
            if self.function_analyzer and hasattr(func_type, "mutability"):
                from vyper.builtins.functions import RawCall

                if isinstance(func_type, RawCall):
                    # as opposed to other functions, raw_call's mutability
                    # depends on its arguments, so we need to determine
                    # it at each call site.
                    mutability = func_type.get_mutability_at_call_site(node)
                else:
                    mutability = func_type.mutability
                self._check_call_mutability(mutability)  # type: ignore

            arg_types = func_type.infer_arg_types(node, expected_return_typ=typ)  # type: ignore
            for arg, arg_type in zip(node.args, arg_types):
                self.visit(arg, arg_type)
            kwarg_types = func_type.infer_kwarg_types(node)  # type: ignore
            for kwarg in node.keywords:
                self.visit(kwarg.value, kwarg_types[kwarg.arg])

        self.visit(node.func, func_type)

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
                    # flag membership - `some_flag in other_flag`
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
        if self.func and self.func.mutability == StateMutability.PURE:
            _validate_pure_access(node, typ)

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

        if isinstance(base_type, HashMapT):
            index_type = base_type.key_type
        else:
            # Arrays allow most int types as index: Take the least specific
            index_type = get_possible_types_from_node(node.slice).pop()

        self.visit(node.value, base_type)
        self.visit(node.slice, index_type)

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
    start, end = [i.reduced() for i in (start, end)]

    if "bound" in kwargs:
        bound = kwargs["bound"].reduced()
        if not isinstance(bound, vy_ast.Int):
            raise StructureException("Bound must be a literal integer", bound)
        if bound.value <= 0:
            raise StructureException("Bound must be at least 1", bound)
        if isinstance(start, vy_ast.Int) and isinstance(end, vy_ast.Int):
            error = "Please remove the `bound=` kwarg when using range with constants"
            raise StructureException(error, bound)
    else:
        for arg in (start, end):
            if not isinstance(arg, vy_ast.Int):
                error = "Value must be a literal integer, unless a bound is specified"
                raise StructureException(error, arg)
        if end.value <= start.value:
            raise StructureException("End must be greater than start", end)

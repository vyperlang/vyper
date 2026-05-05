from __future__ import annotations

from itertools import zip_longest
from typing import Optional

from vyper import ast as vy_ast
from vyper.evm.opcodes import version_check
from vyper.compiler.settings import get_global_settings
from vyper.exceptions import (
    BorrowException,
    CallViolation,
    CompilerPanic,
    EvmVersionException,
    ExceptionList,
    FeatureException,
    FunctionDeclarationException,
    ImmutableViolation,
    InitializerException,
    InterfaceViolation,
    InvalidLiteral,
    InvalidType,
    StateAccessViolation,
    StructureException,
    UndeclaredDefinition,
    VyperException,
    tag_exceptions,
)
from vyper.semantics.analysis.base import (
    ExportsInfo,
    ImportInfo,
    InitializesInfo,
    Modifiability,
    ModuleInfo,
    ModuleOwnership,
    StateMutability,
    UsesInfo,
    VarInfo,
)
from vyper.semantics.analysis.common import VyperNodeVisitorBase
from vyper.semantics.analysis.constant_folding import constant_fold
from vyper.semantics.analysis.getters import generate_public_variable_getters
from vyper.semantics.analysis.imports import ImportAnalyzer
from vyper.semantics.analysis.levenshtein_utils import get_levenshtein_error_suggestions
from vyper.semantics.analysis.local import ExprVisitor, analyze_functions, check_module_uses
from vyper.semantics.analysis.utils import (
    check_modifiability,
    get_exact_type_from_node,
    get_expr_info,
    structurally_equivalent,
)
from vyper.semantics.data_locations import DataLocation
from vyper.semantics.namespace import Namespace, get_namespace, override_global_namespace
from vyper.semantics.types import TYPE_T, EventT, FlagT, InterfaceT, StructT, VyperType, is_type_t
from vyper.semantics.types.function import ContractFunctionT, KeywordArg, _FunctionArg
from vyper.semantics.types.module import ModuleT
from vyper.semantics.types.utils import type_from_annotation
from vyper.utils import OrderedSet


def analyze_modules(imports: ImportAnalyzer) -> ModuleT:
    """
    Analyze Vyper module ASTs, add all module-level objects to the namespace,
    type-check/validate semantics and annotate with type and analysis info.
    """
    root_module_ast = imports.toplevel_module

    modules = imports.seen
    """
    Comes from ImportAnalyzer, guarantees that:
    1. they are sorted in the post-order of the import tree:
        each module comes after every one of its imports.
    2. there is only a single root:
        each module is imported by another one, except for a single module
    """

    # TODO: Instead of being recursive, use `modules`
    # Collect module members, partial validation
    ret = _compute_module_type_r(root_module_ast)

    for module_ast in modules:
        _check_overrides(module_ast)

    # Remainder of validation: everything that requires module-level/cross-module information
    # Notably function bodies

    # These must be two different loops, because of cross-module calls and abstract resolution
    for module_ast in modules:
        _build_call_graph_edges(module_ast)

    for module_ast in modules:
        _analyze_call_graph(module_ast)

    for module_ast in modules:
        _analyze_module_bodies(module_ast)

    # check for event name collisions between defined and used events
    # (needs to be after reachable set with overrides computation since used_events depends on it)
    for module_ast in modules:
        module_ast._metadata["type"].validate_used_events()

    root_module_t = root_module_ast._metadata["type"]

    # Errors out if decimals are used, but not enabled
    settings = get_global_settings()
    if settings and not settings.get_enable_decimals():
        if any(func_t.uses_decimal() for func_t in root_module_t.reachable_functions):
            raise FeatureException("decimals are not allowed unless `--enable-decimals` is set")

    return ret


def _compute_module_type_r(module_ast: vy_ast.Module) -> ModuleT:
    """validate semantics and annotate AST with type/semantics information"""

    if "type" in module_ast._metadata:
        # we don't need to analyse again, skip out
        assert isinstance(module_ast._metadata["type"], ModuleT)
        return module_ast._metadata["type"]

    # validate semantics and annotate AST with type/semantics information
    namespace = get_namespace()

    with namespace.enter_scope():
        analyzer = ModuleAnalyzer(module_ast, namespace)
        analyzer.analyze_module_body()

        generate_public_variable_getters(module_ast)

        ret = ModuleT(module_ast)
        module_ast._metadata["type"] = ret

    return ret


def _analyze_module_bodies(module_ast: vy_ast.Module) -> None:
    """
    Use module types to validate function bodies
    Also sets type metadata for nodes therein
    """
    # interfaces don't have function bodies to validate
    if module_ast.is_interface:
        return

    module_t = module_ast._metadata["type"]
    namespace = module_ast._metadata["namespace"]

    with override_global_namespace(namespace):
        analyze_functions(module_ast)
        _validate_exports_uses(module_ast, module_t)
        _validate_initialized_modules(module_ast, module_t)
        _validate_used_modules(module_ast, module_t)


def _validate_used_modules(module_ast: vy_ast.Module, module_t: ModuleT) -> None:
    """Check all `uses:` modules are actually used."""
    should_use = {}

    uses_decls = module_t.uses_decls
    for decl in uses_decls:
        info = decl._metadata["uses_info"]
        for m in info.used_modules:
            should_use[m.module_t] = (m, info)

    initialized_modules = {t.module_info.module_t: t for t in module_t.initialized_modules}

    all_used_modules: OrderedSet[ModuleT] = OrderedSet()

    for f in module_t.functions.values():
        for u in f.get_used_modules():
            all_used_modules.add(u.module_t)

    for decl in module_t.exports_decls:
        info = decl._metadata["exports_info"]
        all_used_modules.update([u.module_t for u in info.used_modules])

    for used_module in all_used_modules:
        if used_module in initialized_modules:
            continue

        if used_module in should_use:
            del should_use[used_module]

    if len(should_use) > 0:
        err_list = ExceptionList()
        for used_module_info, uses_info in should_use.values():
            msg = f"`{used_module_info.alias}` is declared as used, but "
            msg += f"its state is not actually used in {module_t}!"
            hint = f"delete `uses: {used_module_info.alias}`"
            err_list.append(BorrowException(msg, uses_info.node, hint=hint))

        err_list.raise_if_not_empty()


def _validate_initialized_modules(module_ast: vy_ast.Module, module_t: ModuleT) -> None:
    """Check all `initializes:` modules have `__init__()` called exactly once."""
    # only call `__init__()` for modules which have an
    # `__init__()` function
    should_initialize = {
        t.module_info.module_t: t
        for t in module_t.initialized_modules
        if t.module_info.module_t.init_function is not None
    }

    constructor = module_t.init_function

    # Methods called by the constructor
    init_calls: list[vy_ast.Call] = []
    if constructor is not None:
        init_calls = constructor.ast_def.get_descendants(vy_ast.Call)  # type: ignore

    seen_initializers: dict[ModuleT, vy_ast.VyperNode] = {}
    for call_node in init_calls:
        expr_info = call_node.func._expr_info
        if expr_info is None:
            # this can happen for range() calls; CMC 2024-02-05 try to
            # refactor so that range() is properly tagged.
            continue

        call_t = expr_info.typ

        if not isinstance(call_t, ContractFunctionT):
            continue

        if not call_t.is_constructor:
            continue

        # XXX: check this works as expected for nested attributes
        initialized_module = call_node.func.value._expr_info.module_info  # type: ignore

        if initialized_module.module_t in seen_initializers:
            seen_location = seen_initializers[initialized_module.module_t]
            msg = f"tried to initialize `{initialized_module.alias}`, "
            msg += "but its __init__() function was already called!"
            raise InitializerException(msg, call_node.func, seen_location)

        if initialized_module.module_t not in should_initialize:
            msg = f"tried to initialize `{initialized_module.alias}`, "
            msg += "but it is not in initializer list!"
            hint = f"add `initializes: {initialized_module.alias}` "
            hint += "as a top-level statement to your contract"
            raise InitializerException(msg, call_node.func, hint=hint)

        del should_initialize[initialized_module.module_t]
        seen_initializers[initialized_module.module_t] = call_node.func

    if len(should_initialize) > 0:
        err_list = ExceptionList()
        for s in should_initialize.values():
            msg = "not initialized!"
            hint = f"add `{s.module_info.alias}.__init__()` to "
            hint += "your `__init__()` function"

            # grab the init function AST node for error message
            # (it could be None, it's ok since it's just for diagnostics)
            init_func_node = None
            if constructor is not None:
                init_func_node = constructor.decl_node
            err_list.append(InitializerException(msg, init_func_node, s.node, hint=hint))

        err_list.raise_if_not_empty()


def _validate_exports_uses(module_ast: vy_ast.Module, module_t: ModuleT) -> None:
    """
    Check that exported functions that use state have proper `uses:` declarations.

    This is deferred from visit_ExportsDecl because uses_state() requires
    reachable_internal_functions which is populated during body analysis.
    """
    for decl in module_t.exports_decls:
        info = decl._metadata["exports_info"]
        for func_t in info.functions:
            export_node = info.functions.get(func_t)
            if export_node is None:
                continue

            with tag_exceptions(export_node):
                if func_t.uses_state():
                    module_info = check_module_uses(export_node)

                    # guaranteed by earlier checks in visit_ExportsDecl:
                    assert module_info is not None

                    info.used_modules.add(module_info)


def _build_call_graph_edges(module_ast: vy_ast.Module):
    # get list of internal function calls made by each function
    # CMC 2024-02-03 note: this could be cleaner in analysis/local.py
    with override_global_namespace(module_ast._metadata["namespace"]):
        function_defs = module_ast.get_children(vy_ast.FunctionDef)

        for func in function_defs:
            fn_t = func._metadata["func_type"]
            assert len(fn_t.called_functions) == 0
            fn_t.called_functions = OrderedSet()

            function_calls = func.get_descendants(vy_ast.Call)

            for call in function_calls:
                try:
                    call_t = get_exact_type_from_node(call.func)
                except VyperException:
                    # there is a problem getting the call type. this might be
                    # an issue, but it will be handled properly later. right now
                    # we just want to be able to construct the call graph.
                    continue

                if isinstance(call_t, ContractFunctionT) and (
                    call_t.is_internal or call_t.is_constructor
                ):
                    # Call graph is defined in terms of concrete functions (i.e. non-abstract)
                    fn_t.called_functions.add(call_t.get_concrete_override())


def _analyze_call_graph(module_ast: vy_ast.Module):
    """
    1. compute reachable set tag in each fn_t's reachable_internal_functions
    2. validate no call cycles
    3. validate nonreentrant functions not reachable from nonreentrant functions
    """
    function_defs = module_ast.get_children(vy_ast.FunctionDef)

    for func in function_defs:
        fn_t = func._metadata["func_type"]

        # compute reachable set and validate the call graph
        _compute_and_validate_reachable_r(fn_t)

        if fn_t.nonreentrant:
            for g in fn_t.reachable_internal_functions:
                if g.nonreentrant:
                    # TODO: improve the error message by displaying the exact
                    # path through the call graph
                    msg = f"Cannot call `{g.name}` since it is"
                    msg += f" `@nonreentrant` and reachable from `{fn_t.name}`"
                    msg += ", which is also marked `@nonreentrant`"
                    raise CallViolation(msg, func, g.ast_def)


def _compute_and_validate_reachable_r(
    fn_t: ContractFunctionT, path: list[ContractFunctionT] = None
) -> None:
    """
    compute reachable set and validate acyclicity for a given fn_t
    """
    path = path or []

    path.append(fn_t)

    for g in fn_t.called_functions:
        if g in fn_t.reachable_internal_functions:
            # already seen
            continue

        if g in path:
            extended_path = path + [g]
            message = " -> ".join([f.name for f in extended_path])
            raise CallViolation(f"Contract contains cyclic function call: {message}")

        _compute_and_validate_reachable_r(g, path=path)

        g_reachable = g.reachable_internal_functions
        assert fn_t not in g_reachable  # sanity check
        fn_t.reachable_internal_functions.update(g_reachable)

        fn_t.reachable_internal_functions.add(g)

    path.pop()


def _validate_overrides(func_t: ContractFunctionT, node: vy_ast.FunctionDef):
    """Validate @override decorators and set `overridden_by` on abstract methods."""
    for override_name in func_t.override_nodes:
        try:
            module_info = get_namespace()[override_name.id]
        except KeyError:
            # Module is not imported, error will be reported elsewhere
            continue

        if not isinstance(module_info, ModuleInfo):
            raise FunctionDeclarationException(
                f"`{override_name.id}` is not a module", override_name
            )

        if module_info.ownership != ModuleOwnership.INITIALIZES:
            msg = f"Cannot override `{module_info.alias}.{node.name}`"
            msg += " as it is not initialized"
            hint = f"add `initializes: {module_info.alias}` "
            hint += f"as a top-level statement in {node.module_node.path}"
            raise FunctionDeclarationException(msg, node, hint=hint)

        abstract_t = module_info.module_t.functions.get(node.name)

        if abstract_t is None:
            msg = f"Tried to override `{module_info.alias}.{node.name}`,"
            msg += " but it does not exist"
            lev_hint = get_levenshtein_error_suggestions(
                node.name, module_info.module_t.functions, 0.3
            )
            raise FunctionDeclarationException(msg, node, hint=lev_hint)

        abstract_fn = abstract_t.ast_def

        if not abstract_t.is_abstract:
            msg = f"Cannot override `{module_info.alias}.{node.name}`,"
            msg += " it is not an abstract method!"
            raise FunctionDeclarationException(msg, abstract_fn, node)

        if abstract_t._overridden_by is not None:
            existing_override = abstract_t._overridden_by.ast_def
            existing_override_path = existing_override.module_node.path
            msg = f"`{module_info.alias}.{node.name}` was already overridden"
            msg += f" in `{existing_override_path}`!"
            hint = f"the likely root cause is that `{module_info.alias}` has"
            hint += f" been initialized in both `{node.module_node.path}` and"
            hint += f" `{existing_override_path}`, which is an error"
            raise FunctionDeclarationException(
                msg, abstract_fn, existing_override, override_name, hint=hint
            )

        abstract_t.set_overridden_by(func_t)


class ModuleAnalyzer(VyperNodeVisitorBase):
    scope_name = "module"

    def __init__(self, module_node: vy_ast.Module, namespace: Namespace) -> None:
        self.ast = module_node
        self.namespace = namespace

        # keep track of exported functions to prevent duplicate exports
        self._all_functions: dict[ContractFunctionT, vy_ast.VyperNode] = {}

        # keep track of implemented modules to prevent duplicates
        self._all_implements: dict[VyperType, vy_ast.VyperNode] = {}

        self._events: list[EventT] = []

        self.module_t: Optional[ModuleT] = None

    def analyze_module_body(self):
        # generate a `ModuleT` from the top-level node
        # note: also validates unique method ids

        assert "type" not in self.ast._metadata

        self._to_visit = self.ast.body.copy()

        # handle imports
        self._visit_nodes_linear((vy_ast.Import, vy_ast.ImportFrom))

        # we can resolve constants as soon as imports are handled.
        constant_fold(self.ast)

        # handle ownership decls, mutate ModuleInfo.ownership
        self._visit_nodes_linear((vy_ast.UsesDecl, vy_ast.InitializesDecl))

        # handle some node types using a dependency resolution routine
        # which loops, swallowing exceptions until all nodes are processed
        type_decls = (vy_ast.FlagDef, vy_ast.StructDef, vy_ast.InterfaceDef, vy_ast.EventDef)
        self._visit_nodes_looping(type_decls)

        # handle functions
        # run before exports for exception handling priority
        self._visit_nodes_looping((vy_ast.VariableDecl, vy_ast.FunctionDef))

        # mutates _exposed_functions
        self._visit_nodes_linear(vy_ast.ExportsDecl)

        # handle implements last, after all functions are handled
        self._visit_nodes_linear(vy_ast.ImplementsDecl)

        # we are done! any remaining nodes should raise errors; visit
        # them to trip the exception.
        for n in self._to_visit:
            self.visit(n)

        # attach namespace to the module for downstream use.
        _ns = Namespace()
        # note that we don't just copy the namespace because
        # there are constructor issues.
        _ns.update({k: self.namespace[k] for k in self.namespace._scopes[-1]})  # type: ignore
        _ns._scopes = self.namespace._scopes.copy()
        self.ast._metadata["namespace"] = _ns

    def _visit_nodes_linear(self, node_type):
        for node in self._to_visit.copy():
            if not isinstance(node, node_type):
                continue
            self.visit(node)
            self._to_visit.remove(node)

    # visit nodes which may have dependencies on each other
    def _visit_nodes_looping(self, node_type):
        nodes = [n for n in self._to_visit if isinstance(n, node_type)]

        # keep trying to process all the nodes until we finish or can
        # no longer progress. this makes it so we don't need to
        # calculate a dependency tree between top-level items.
        # note that the nodes processed here should not mutate ModuleAnalyzer
        # state, otherwise ModuleAnalyzer state can end up invalid!
        while len(nodes) > 0:
            count = len(nodes)
            err_list = ExceptionList()
            for node in nodes.copy():
                try:
                    self.visit(node)
                    nodes.remove(node)
                    self._to_visit.remove(node)
                except (InvalidLiteral, InvalidType) as e:
                    # these exceptions cannot be caused by another statement
                    # not yet being parsed, so we raise them immediately
                    raise e from None
                except VyperException as e:
                    err_list.append(e)

            # Only raise if no nodes were successfully processed. This allows
            # module level logic to parse regardless of the ordering of code
            # elements.
            if count == len(nodes):
                err_list.raise_if_not_empty()

    def visit_ImplementsDecl(self, node):
        interface_types = list()
        for name in node.children:
            type_ = type_from_annotation(name)

            if type_ in self._all_implements:
                msg = f"{name.id} implemented more than once"
                hint = None
                raise StructureException(msg, self._all_implements[type_], name, hint=hint)

            self._all_implements[type_] = name

            if not isinstance(type_, InterfaceT):
                msg = "Not an interface!"
                hint = None
                if isinstance(type_, ModuleT):
                    path = type_._module.path
                    msg += " (Since vyper v0.4.0, interface files are required"
                    msg += " to have a .vyi suffix.)"
                    hint = f"try renaming `{path}` to `{path}i`"
                raise StructureException(msg, name, hint=hint)

            # grab exposed functions
            funcs = {fn_t: node for fn_t, node in self._all_functions.items() if fn_t.is_external}
            type_.validate_implements(node, funcs)

            interface_types.append(type_)

        node._metadata["interface_types"] = interface_types

    def visit_UsesDecl(self, node):
        # TODO: check duplicate uses declarations, e.g.
        # uses: x
        # ...
        # uses: x
        items = vy_ast.as_tuple(node.annotation)

        used_modules = []

        for item in items:
            module_info = get_expr_info(item).module_info
            if module_info is None:
                raise StructureException("not a valid module!", item)

            # note: try to refactor - not a huge fan of mutating the
            # ModuleInfo after it's constructed
            module_info.set_ownership(ModuleOwnership.USES, item)

            used_modules.append(module_info)

        node._metadata["uses_info"] = UsesInfo(used_modules, node)

    def visit_InitializesDecl(self, node):
        annotation = node.annotation

        dependencies_ast = ()
        module_ref = annotation
        if isinstance(module_ref, vy_ast.Subscript):
            dependencies_ast = vy_ast.as_tuple(module_ref.slice)
            module_ref = module_ref.value

        # postcondition of InitializesDecl.validates()
        assert isinstance(module_ref, (vy_ast.Name, vy_ast.Attribute))

        module_info = get_expr_info(module_ref).module_info
        if module_info is None:
            raise StructureException("Not a module!", module_ref)

        used_modules = {i.module_t: i for i in module_info.module_t.used_modules}

        dependencies = []
        for named_expr in dependencies_ast:
            assert isinstance(named_expr, vy_ast.NamedExpr)

            rhs_module = get_expr_info(named_expr.value).module_info

            with module_info.module_node.namespace():
                # lhs of the named_expr is evaluated in the namespace of the
                # initialized module!
                try:
                    lhs_module = get_expr_info(named_expr.target).module_info
                except VyperException as e:
                    # try to report a common problem - user names the module in
                    # the current namespace instead of the initialized module
                    # namespace.

                    # search for the module in the initialized module
                    found_module = module_info.module_t.find_module_info(rhs_module.module_t)
                    if found_module is not None:
                        msg = f"unknown module `{named_expr.target.id}`"
                        hint = f"did you mean `{found_module.alias} := {rhs_module.alias}`?"
                        raise UndeclaredDefinition(msg, named_expr.target, hint=hint)

                    raise e from None

            if lhs_module.module_t != rhs_module.module_t:
                raise StructureException(
                    f"{lhs_module.alias} is not {rhs_module.alias}!", named_expr
                )
            dependencies.append(lhs_module)

            if lhs_module.module_t not in used_modules:
                raise InitializerException(
                    f"`{module_info.alias}` is initialized with `{lhs_module.alias}`, "
                    f"but `{module_info.alias}` does not use `{lhs_module.alias}`!",
                    named_expr,
                )

            del used_modules[lhs_module.module_t]

        if len(used_modules) > 0:
            item = next(iter(used_modules.values()))  # just pick one
            msg = f"`{module_info.alias}` uses `{item.alias}`, but it is not "
            msg += f"initialized with `{item.alias}`"

            lhs = item.alias
            rhs = None
            # find the alias of the uninitialized module in this contract
            # to fill out the error message with.
            for k, v in self.namespace.items():
                if isinstance(v, ModuleInfo) and v.module_t == item.module_t:
                    rhs = k
                    break

            if rhs is None:
                hint = f"try importing `{item.alias}` first "
                hint += f"(located at `{item.module_t._module.path}`)"
            elif not isinstance(annotation, vy_ast.Subscript):
                # it's `initializes: foo` instead of `initializes: foo[...]`
                hint = f"did you mean {module_ref.id}[{lhs} := {rhs}]?"
            else:
                hint = f"add `{lhs} := {rhs}` to its initializer list"
            raise InitializerException(msg, node, hint=hint)

        # note: try to refactor. not a huge fan of mutating the
        # ModuleInfo after it's constructed
        module_info.set_ownership(ModuleOwnership.INITIALIZES, node)
        node._metadata["initializes_info"] = InitializesInfo(module_info, dependencies, node)

    def visit_ExportsDecl(self, node):
        export_annotations = vy_ast.as_tuple(node.annotation)
        exported_funcs: dict[ContractFunctionT, vy_ast.VyperNode] = {}

        # CMC 2024-04-13 TODO: reduce nesting in this function

        for export_ann in export_annotations:
            # set is_callable=True to give better error messages for imported
            # types, e.g. exports: some_module.MyEvent
            info = get_expr_info(export_ann, is_callable=True)

            if info.var_info is not None:
                decl = info.var_info.decl_node
                if not info.var_info.is_public:
                    raise StructureException("not a public variable!", decl, export_ann)
                funcs = [decl._expanded_getter._metadata["func_type"]]
            elif isinstance(info.typ, ContractFunctionT):
                # e.g. lib1.__interface__(self._addr).foo
                if not isinstance(get_expr_info(export_ann.value).typ, (ModuleT, TYPE_T)):
                    raise StructureException(
                        "invalid export of a value",
                        export_ann.value,
                        hint="exports should look like <module>.<function | interface>",
                    )

                # regular function
                funcs = [info.typ]
            elif is_type_t(info.typ, InterfaceT):
                interface_t = info.typ.typedef

                if not isinstance(export_ann, vy_ast.Attribute):
                    raise StructureException(
                        "invalid export",
                        hint="exports should look like <module>.<function | interface>",
                    )

                module_info = get_expr_info(export_ann.value).module_info
                if module_info is None:
                    raise StructureException("not a valid module!", export_ann.value)

                if interface_t not in module_info.typ.implemented_interfaces:
                    iface_str = export_ann.node_source_code
                    module_str = export_ann.value.node_source_code
                    msg = f"requested `{iface_str}` but `{module_str}`"
                    msg += f" does not implement `{iface_str}`!"
                    raise InterfaceViolation(msg, export_ann)

                module_exposed_fns = {fn.name: fn for fn in module_info.typ.exposed_functions}
                # find the specific implementation of the function in the module
                funcs = [
                    module_exposed_fns[fn.name]
                    for fn in interface_t.functions.values()
                    if fn.is_external
                ]

                if len(funcs) == 0:
                    path = module_info.module_node.path
                    msg = f"{module_info.alias} (located at `{path}`) has no external functions!"
                    raise StructureException(msg, export_ann)

            else:
                raise StructureException(
                    f"not a function or interface: `{info.typ}`", info.typ.decl_node, export_ann
                )

            for func_t in funcs:
                if not func_t.is_external:
                    raise StructureException(
                        "can't export non-external functions!", func_t.decl_node, export_ann
                    )

                self._add_exposed_function(func_t, export_ann, relax=False)
                with tag_exceptions(export_ann):  # tag exceptions with specific export
                    self._self_t.typ.add_member(func_t.name, func_t)

                    exported_funcs[func_t] = export_ann

        node._metadata["exports_info"] = ExportsInfo(functions=exported_funcs)

    @property
    def _self_t(self):
        return self.namespace["self"]

    def _add_exposed_function(self, func_t, node, relax=True):
        # call this before self._self_t.typ.add_member() for exception raising
        # priority
        if not relax and (prev_decl := self._all_functions.get(func_t)) is not None:
            raise StructureException("already exported!", node, prev_decl=prev_decl)

        self._all_functions[func_t] = node

    def visit_VariableDecl(self, node):
        # postcondition of VariableDecl.validate
        assert isinstance(node.target, vy_ast.Name)
        name = node.target.id

        if not self.ast.settings.nonreentrancy_by_default and node.is_reentrant:
            raise StructureException(
                "reentrant() is not allowed without `pragma nonreentrancy on`", node
            )

        # TODO: move this check to local analysis
        if node.is_immutable:
            # mutability is checked automatically preventing assignment
            # outside of the constructor, here we just check a value is assigned,
            # not necessarily where
            assignments = self.ast.get_descendants(
                vy_ast.Assign, filters={"target.id": node.target.id}
            )
            if not assignments:
                # Special error message for common wrong usages via `self.<immutable name>`
                wrong_self_attribute = self.ast.get_descendants(
                    vy_ast.Attribute, {"value.id": "self", "attr": node.target.id}
                )
                message = (
                    "Immutable variables must be accessed without 'self'"
                    if len(wrong_self_attribute) > 0
                    else "Immutable definition requires an assignment in the constructor"
                )
                raise ImmutableViolation(message, node)

        location = (
            DataLocation.CODE
            if node.is_immutable
            else DataLocation.UNSET
            if node.is_constant
            else DataLocation.TRANSIENT
            if node.is_transient
            else DataLocation.STORAGE
        )

        modifiability = (
            Modifiability.RUNTIME_CONSTANT
            if node.is_immutable
            else Modifiability.CONSTANT
            if node.is_constant
            else Modifiability.MODIFIABLE
        )

        type_ = type_from_annotation(node.annotation, location)

        if node.is_transient and not version_check(begin="cancun"):
            raise EvmVersionException("`transient` is not available pre-cancun", node.annotation)

        var_info = VarInfo(
            type_,
            decl_node=node,
            location=location,
            modifiability=modifiability,
            is_public=node.is_public,
        )
        node.target._metadata["varinfo"] = var_info  # TODO maybe put this in the global namespace
        node._metadata["type"] = type_
        node.target._metadata["type"] = type_

        if node.is_public:
            # generate function type and add to metadata
            # we need this when building the public getter
            func_t = ContractFunctionT.getter_from_VariableDecl(node)
            node._metadata["getter_type"] = func_t
            self._add_exposed_function(func_t, node)

        def _finalize():
            # add the variable name to `self` namespace if the variable is either
            # 1. a public constant or immutable; or
            # 2. a storage variable, whether private or public
            if (node.is_constant or node.is_immutable) and not node.is_public:
                return

            self._self_t.typ.add_member(name, var_info)
            node.target._metadata["type"] = type_

        def _validate_self_namespace():
            # block globals if storage variable already exists
            self._self_t.typ._check_add_member(name)
            self.namespace[name] = var_info

        if node.is_constant:
            assert node.value is not None  # checked in VariableDecl.validate()
            ExprVisitor().visit(node.value, type_)  # performs validate_expected_type

            if not check_modifiability(node.value, Modifiability.CONSTANT):
                raise StateAccessViolation("Value must be a literal", node.value)

            _validate_self_namespace()

            return _finalize()

        assert node.value is None  # checked in VariableDecl.validate()
        if node.is_immutable:
            _validate_self_namespace()
            return _finalize()

        self.namespace.validate_assignment(name)

        return _finalize()

    def visit_FlagDef(self, node):
        obj = FlagT.from_FlagDef(node)
        node._metadata["flag_type"] = obj
        self.namespace[node.name] = obj

    def visit_EventDef(self, node):
        obj = EventT.from_EventDef(node)
        node._metadata["event_type"] = obj
        self.namespace[node.name] = obj
        self._events.append(obj)

    def visit_FunctionDef(self, node):
        if self.ast.is_interface:
            func_t = ContractFunctionT.from_vyi(node)
            if not func_t.is_external:
                # TODO test me!
                raise StructureException(
                    "Internal functions in `.vyi` files are not allowed!", node
                )
        else:
            func_t = ContractFunctionT.from_FunctionDef(node)
            _validate_overrides(func_t, node)

        self._self_t.typ.add_member(func_t.name, func_t)
        node._metadata["func_type"] = func_t
        self._add_exposed_function(func_t, node)

    def visit_Import(self, node):
        self._add_import(node)

    def visit_ImportFrom(self, node):
        self._add_import(node)

    def _add_import(self, node: vy_ast.Import | vy_ast.ImportFrom) -> None:
        for import_info in node._metadata["import_infos"]:
            # similar structure to import analyzer
            module_info = self._load_import(import_info)

            import_info._typ = module_info

            self.namespace[import_info.alias] = module_info

    def _load_import(self, import_info: ImportInfo) -> ModuleInfo | InterfaceT:
        path = import_info.compiler_input.path
        if path.suffix == ".vy":
            module_ast = import_info.parsed
            with override_global_namespace(Namespace()):
                module_t = _compute_module_type_r(module_ast)
                return ModuleInfo(module_t, import_info.alias)

        if path.suffix == ".vyi":
            module_ast = import_info.parsed
            with override_global_namespace(Namespace()):
                module_t = _compute_module_type_r(module_ast)

                # NOTE: might be cleaner to return the whole module, so we
                # have a ModuleInfo, that way we don't need to have different
                # code paths for InterfaceT vs ModuleInfo
                return module_t.interface

        if path.suffix == ".json":
            abi = import_info.parsed
            path = import_info.compiler_input.path
            return InterfaceT.from_json_abi(str(path), abi)

        raise CompilerPanic("unreachable")  # pragma: nocover

    def visit_InterfaceDef(self, node):
        interface_t = InterfaceT.from_InterfaceDef(node)
        node._metadata["interface_type"] = interface_t
        self.namespace[node.name] = interface_t

    def visit_StructDef(self, node):
        struct_t = StructT.from_StructDef(node)
        node._metadata["struct_type"] = struct_t
        self.namespace[node.name] = struct_t


def _pretty_param(param: _FunctionArg) -> str:
    return f"`{param.name}: {param.typ}`"


def _default_values_match(p_override: _FunctionArg, p_abstract: _FunctionArg) -> bool:
    if isinstance(p_abstract, KeywordArg):
        if not isinstance(p_override, KeywordArg):
            # Default cannot be overridden by non-default
            return False

        if isinstance(p_abstract.default_value, vy_ast.Ellipsis):
            # `...` default can be overridden by any default
            return True

        # other defaults must match exactly, 1 + 1 cannot be overridden by 2
        return structurally_equivalent(p_abstract.default_value, p_override.default_value)
    else:
        # Non-default can be overridden by both default and non-default
        return True


def _parameter_override_discrepancy(
    override_t: ContractFunctionT,
    abstract_t: ContractFunctionT,
    p_override: _FunctionArg,
    p_abstract: Optional[_FunctionArg],
) -> Optional[VyperException]:
    if p_abstract is None:
        if isinstance(p_override, KeywordArg):
            # matches
            return None

        return FunctionDeclarationException(
            f"{override_t.name} has mandatory parameter {_pretty_param(p_override)} "
            "not present in the method it overrides",
            abstract_t.ast_def,
            p_override.ast_source,
            hint="remove the extra parameter, or add a default value",
        )

    if (
        p_override.name == p_abstract.name
        and p_override.typ.is_supertype_of(p_abstract.typ)
        and _default_values_match(p_override, p_abstract)
    ):
        return None

    return FunctionDeclarationException(
        "Override parameter mismatch: "
        f"Got {_pretty_param(p_override)}, "
        f"but expected {_pretty_param(p_abstract)} (or more general)",
        p_override.ast_source,
        p_abstract.ast_source,
    )


# note: substantial overlap with ContractFunctionT.implements and
# ModuleT.validate_implements -- refactor to use common logic.
def _compute_override_discrepancies(
    override_t: ContractFunctionT, abstract_t: ContractFunctionT
) -> ExceptionList:
    assert override_t.is_internal
    assert abstract_t.is_internal
    assert abstract_t.is_abstract

    parameters_override = override_t.arguments
    return_o = override_t.return_type

    parameters_abstract = abstract_t.arguments
    return_a = abstract_t.return_type

    discrepancies: ExceptionList = ExceptionList()

    # Parameter validation

    if len(parameters_override) < len(parameters_abstract):
        msg = f"{override_t.name} has {len(parameters_override)} params,"
        msg += f" but it should have at least {len(parameters_abstract)}"
        discrepancies.append(
            FunctionDeclarationException(msg, override_t.ast_def, abstract_t.ast_def)
        )
    else:
        for p_override, p_abstract in zip_longest(parameters_override, parameters_abstract):
            discrepancy = _parameter_override_discrepancy(
                override_t, abstract_t, p_override, p_abstract
            )

            if discrepancy is not None:
                discrepancies.append(discrepancy)

    # Return type validation

    neither_returns = return_a is None and return_o is None

    both_return_and_match = (
        return_a is not None and return_o is not None and return_o.is_subtype_of(return_a)
    )

    return_types_match = both_return_and_match or neither_returns

    if not return_types_match:
        return_o_str = "does not return anything" if return_o is None else f"returns {return_o}"
        return_a_str = "does not return anything" if return_a is None else f"returns {return_a}"
        msg = f"{override_t.name} {return_o_str} but the method it overrides {return_a_str}"
        discrepancies.append(
            FunctionDeclarationException(msg, abstract_t.ast_def, override_t.ast_def)
        )

    # Mutability validation

    if override_t.mutability > abstract_t.mutability:
        # There is nothing stricter than @pure
        or_stricter = " (or stricter)" if abstract_t.mutability != StateMutability.PURE else ""
        msg = f"{override_t.name} is {override_t.mutability} but it overrides a"
        msg += f" {abstract_t.mutability} method"

        hint = f"change {override_t.name} to be {abstract_t.mutability}{or_stricter}"

        discrepancies.append(
            FunctionDeclarationException(msg, abstract_t.ast_def, override_t.ast_def, hint=hint)
        )

    # Reentrancy validation

    if override_t.nonreentrant != abstract_t.nonreentrant:
        reentrancy_o = "non-reentrant" if override_t.nonreentrant else "reentrant"
        reentrancy_a = "non-reentrant" if abstract_t.nonreentrant else "reentrant"

        msg = f"{override_t.name} is {reentrancy_o} but it overrides a"
        msg += f" {reentrancy_a} method"
        discrepancies.append(
            FunctionDeclarationException(msg, abstract_t.ast_def, override_t.ast_def)
        )

    return discrepancies


def _check_overrides(module_ast: vy_ast.Module):
    for func in module_ast.get_children(vy_ast.FunctionDef):
        func_t = func._metadata["func_type"]
        if func_t.is_abstract:
            override_t = func_t.overridden_by

            err_list = _compute_override_discrepancies(override_t, func_t)
            err_list.raise_if_not_empty()

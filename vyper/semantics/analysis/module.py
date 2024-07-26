import os
from pathlib import Path, PurePath
from typing import Any, Optional

import vyper.builtins.interfaces
from vyper import ast as vy_ast
from vyper.compiler.input_bundle import (
    ABIInput,
    CompilerInput,
    FileInput,
    FilesystemInputBundle,
    InputBundle,
    PathLike,
)
from vyper.evm.opcodes import version_check
from vyper.exceptions import (
    BorrowException,
    CallViolation,
    CompilerPanic,
    DuplicateImport,
    EvmVersionException,
    ExceptionList,
    ImmutableViolation,
    InitializerException,
    InterfaceViolation,
    InvalidLiteral,
    InvalidType,
    ModuleNotFound,
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
    UsesInfo,
    VarInfo,
)
from vyper.semantics.analysis.common import VyperNodeVisitorBase
from vyper.semantics.analysis.constant_folding import constant_fold
from vyper.semantics.analysis.getters import generate_public_variable_getters
from vyper.semantics.analysis.import_graph import ImportGraph
from vyper.semantics.analysis.local import ExprVisitor, analyze_functions, check_module_uses
from vyper.semantics.analysis.utils import (
    check_modifiability,
    get_exact_type_from_node,
    get_expr_info,
)
from vyper.semantics.data_locations import DataLocation
from vyper.semantics.namespace import Namespace, get_namespace, override_global_namespace
from vyper.semantics.types import EventT, FlagT, InterfaceT, StructT
from vyper.semantics.types.function import ContractFunctionT
from vyper.semantics.types.module import ModuleT
from vyper.semantics.types.utils import type_from_annotation
from vyper.utils import OrderedSet


def analyze_module(
    module_ast: vy_ast.Module,
    input_bundle: InputBundle,
    import_graph: ImportGraph = None,
    is_interface: bool = False,
) -> ModuleT:
    """
    Analyze a Vyper module AST node, recursively analyze all its imports,
    add all module-level objects to the namespace, type-check/validate
    semantics and annotate with type and analysis info
    """
    if import_graph is None:
        import_graph = ImportGraph()

    return _analyze_module_r(module_ast, input_bundle, import_graph, is_interface)


def _analyze_module_r(
    module_ast: vy_ast.Module,
    input_bundle: InputBundle,
    import_graph: ImportGraph,
    is_interface: bool = False,
):
    if "type" in module_ast._metadata:
        # we don't need to analyse again, skip out
        assert isinstance(module_ast._metadata["type"], ModuleT)
        return module_ast._metadata["type"]

    # validate semantics and annotate AST with type/semantics information
    namespace = get_namespace()

    with namespace.enter_scope(), import_graph.enter_path(module_ast):
        analyzer = ModuleAnalyzer(module_ast, input_bundle, namespace, import_graph, is_interface)
        analyzer.analyze_module_body()

        _analyze_call_graph(module_ast)
        generate_public_variable_getters(module_ast)

        ret = ModuleT(module_ast)
        module_ast._metadata["type"] = ret

        # if this is an interface, the function is already validated
        # in `ContractFunction.from_vyi()`
        if not is_interface:
            analyze_functions(module_ast)
            analyzer.validate_initialized_modules()
            analyzer.validate_used_modules()

    return ret


def _analyze_call_graph(module_ast: vy_ast.Module):
    # get list of internal function calls made by each function
    # CMC 2024-02-03 note: this could be cleaner in analysis/local.py
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
                fn_t.called_functions.add(call_t)

    for func in function_defs:
        fn_t = func._metadata["func_type"]

        # compute reachable set and validate the call graph
        _compute_reachable_set(fn_t)


# compute reachable set and validate the call graph (detect cycles)
def _compute_reachable_set(fn_t: ContractFunctionT, path: list[ContractFunctionT] = None) -> None:
    path = path or []

    path.append(fn_t)
    root = path[0]

    for g in fn_t.called_functions:
        if g in fn_t.reachable_internal_functions:
            # already seen
            continue

        if g == root:
            message = " -> ".join([f.name for f in path])
            raise CallViolation(f"Contract contains cyclic function call: {message}")

        _compute_reachable_set(g, path=path)

        g_reachable = g.reachable_internal_functions
        assert fn_t not in g_reachable  # sanity check
        fn_t.reachable_internal_functions.update(g_reachable)

        fn_t.reachable_internal_functions.add(g)

    path.pop()


class ModuleAnalyzer(VyperNodeVisitorBase):
    scope_name = "module"

    def __init__(
        self,
        module_node: vy_ast.Module,
        input_bundle: InputBundle,
        namespace: Namespace,
        import_graph: ImportGraph,
        is_interface: bool = False,
    ) -> None:
        self.ast = module_node
        self.input_bundle = input_bundle
        self.namespace = namespace
        self._import_graph = import_graph
        self.is_interface = is_interface

        # keep track of imported modules to prevent duplicate imports
        self._imported_modules: dict[PurePath, vy_ast.VyperNode] = {}

        # keep track of exported functions to prevent duplicate exports
        self._exposed_functions: dict[ContractFunctionT, vy_ast.VyperNode] = {}

        self._events: list[EventT] = []

        self.module_t: Optional[ModuleT] = None

    def analyze_module_body(self):
        # generate a `ModuleT` from the top-level node
        # note: also validates unique method ids

        assert "type" not in self.ast._metadata

        self._to_visit = self.ast.body.copy()

        # handle imports; mutates `self._imported_modules`
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

    def validate_used_modules(self):
        # check all `uses:` modules are actually used
        should_use = {}

        module_t = self.ast._metadata["type"]
        uses_decls = module_t.uses_decls
        for decl in uses_decls:
            info = decl._metadata["uses_info"]
            for m in info.used_modules:
                should_use[m.module_t] = (m, info)

        initialized_modules = {t.module_info.module_t: t for t in module_t.initialized_modules}

        all_used_modules = OrderedSet()

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

    def validate_initialized_modules(self):
        # check all `initializes:` modules have `__init__()` called exactly once
        module_t = self.ast._metadata["type"]
        should_initialize = {t.module_info.module_t: t for t in module_t.initialized_modules}
        # don't call `__init__()` for modules which don't have
        # `__init__()` function
        for m in should_initialize.copy():
            for f in m.functions.values():
                if f.is_constructor:
                    break
            else:
                del should_initialize[m]

        init_calls = []
        for f in self.ast.get_children(vy_ast.FunctionDef):
            if f._metadata["func_type"].is_constructor:
                init_calls = f.get_descendants(vy_ast.Call)
                break

        seen_initializers = {}
        for call_node in init_calls:
            expr_info = call_node.func._expr_info
            if expr_info is None:
                # this can happen for range() calls; CMC 2024-02-05 try to
                # refactor so that range() is properly tagged.
                continue

            call_t = call_node.func._expr_info.typ

            if not isinstance(call_t, ContractFunctionT):
                continue

            if not call_t.is_constructor:
                continue

            # XXX: check this works as expected for nested attributes
            initialized_module = call_node.func.value._expr_info.module_info

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
                if module_t.init_function:
                    init_func_node = module_t.init_function.decl_node
                err_list.append(InitializerException(msg, init_func_node, s.node, hint=hint))

            err_list.raise_if_not_empty()

    def _ast_from_file(self, file: FileInput) -> vy_ast.Module:
        # cache ast if we have seen it before.
        # this gives us the additional property of object equality on
        # two ASTs produced from the same source
        ast_of = self.input_bundle._cache._ast_of
        if file.source_id not in ast_of:
            ast_of[file.source_id] = _parse_ast(file)

        return ast_of[file.source_id]

    def visit_ImplementsDecl(self, node):
        type_ = type_from_annotation(node.annotation)

        if not isinstance(type_, InterfaceT):
            msg = "Not an interface!"
            hint = None
            if isinstance(type_, ModuleT):
                path = type_._module.path
                msg += " (Since vyper v0.4.0, interface files are required"
                msg += " to have a .vyi suffix.)"
                hint = f"try renaming `{path}` to `{path}i`"
            raise StructureException(msg, node.annotation, hint=hint)

        # grab exposed functions
        funcs = self._exposed_functions
        type_.validate_implements(node, funcs)

        node._metadata["interface_type"] = type_

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
        items = vy_ast.as_tuple(node.annotation)
        exported_funcs = []
        used_modules = OrderedSet()

        # CMC 2024-04-13 TODO: reduce nesting in this function

        for item in items:
            # set is_callable=True to give better error messages for imported
            # types, e.g. exports: some_module.MyEvent
            info = get_expr_info(item, is_callable=True)

            if info.var_info is not None:
                decl = info.var_info.decl_node
                if not info.var_info.is_public:
                    raise StructureException("not a public variable!", decl, item)
                funcs = [decl._expanded_getter._metadata["func_type"]]
            elif isinstance(info.typ, ContractFunctionT):
                # regular function
                funcs = [info.typ]
            elif isinstance(info.typ, InterfaceT):
                if not isinstance(item, vy_ast.Attribute):
                    raise StructureException(
                        "invalid export",
                        hint="exports should look like <module>.<function | interface>",
                    )

                module_info = get_expr_info(item.value).module_info
                if module_info is None:
                    raise StructureException("not a valid module!", item.value)

                if info.typ not in module_info.typ.implemented_interfaces:
                    iface_str = item.node_source_code
                    module_str = item.value.node_source_code
                    msg = f"requested `{iface_str}` but `{module_str}`"
                    msg += f" does not implement `{iface_str}`!"
                    raise InterfaceViolation(msg, item)

                module_exposed_fns = {fn.name: fn for fn in module_info.typ.exposed_functions}
                # find the specific implementation of the function in the module
                funcs = [
                    module_exposed_fns[fn.name]
                    for fn in info.typ.functions.values()
                    if fn.is_external
                ]
            else:
                raise StructureException(
                    f"not a function or interface: `{info.typ}`", info.typ.decl_node, item
                )

            for func_t in funcs:
                if not func_t.is_external:
                    raise StructureException(
                        "can't export non-external functions!", func_t.decl_node, item
                    )

                self._add_exposed_function(func_t, item, relax=False)
                with tag_exceptions(item):  # tag exceptions with specific item
                    self._self_t.typ.add_member(func_t.name, func_t)

                    exported_funcs.append(func_t)

                    # check module uses
                    if func_t.uses_state():
                        module_info = check_module_uses(item)

                        # guaranteed by above checks:
                        assert module_info is not None

                        used_modules.add(module_info)

        node._metadata["exports_info"] = ExportsInfo(exported_funcs, used_modules)

    @property
    def _self_t(self):
        return self.namespace["self"]

    def _add_exposed_function(self, func_t, node, relax=True):
        # call this before self._self_t.typ.add_member() for exception raising
        # priority
        if not relax and (prev_decl := self._exposed_functions.get(func_t)) is not None:
            raise StructureException("already exported!", node, prev_decl=prev_decl)

        self._exposed_functions[func_t] = node

    def visit_VariableDecl(self, node):
        # postcondition of VariableDecl.validate
        assert isinstance(node.target, vy_ast.Name)
        name = node.target.id

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
        if self.is_interface:
            func_t = ContractFunctionT.from_vyi(node)
            if not func_t.is_external:
                # TODO test me!
                raise StructureException(
                    "Internal functions in `.vyi` files are not allowed!", node
                )
        else:
            func_t = ContractFunctionT.from_FunctionDef(node)

        self._self_t.typ.add_member(func_t.name, func_t)
        node._metadata["func_type"] = func_t
        self._add_exposed_function(func_t, node)

    def visit_Import(self, node):
        # import x.y[name] as y[alias]

        alias = node.alias

        if alias is None:
            alias = node.name

        # don't handle things like `import x.y`
        if "." in alias:
            msg = "import requires an accompanying `as` statement"
            suggested_alias = node.name[node.name.rfind(".") :]
            hint = f"try `import {node.name} as {suggested_alias}`"
            raise StructureException(msg, node, hint=hint)

        self._add_import(node, 0, node.name, alias)

    def visit_ImportFrom(self, node):
        # from m.n[module] import x[name] as y[alias]
        alias = node.alias or node.name

        module = node.module or ""
        if module:
            module += "."

        qualified_module_name = module + node.name
        self._add_import(node, node.level, qualified_module_name, alias)

    def visit_InterfaceDef(self, node):
        interface_t = InterfaceT.from_InterfaceDef(node)
        node._metadata["interface_type"] = interface_t
        self.namespace[node.name] = interface_t

    def visit_StructDef(self, node):
        struct_t = StructT.from_StructDef(node)
        node._metadata["struct_type"] = struct_t
        self.namespace[node.name] = struct_t

    def _add_import(
        self, node: vy_ast.VyperNode, level: int, qualified_module_name: str, alias: str
    ) -> None:
        compiler_input, module_info = self._load_import(node, level, qualified_module_name, alias)
        node._metadata["import_info"] = ImportInfo(
            module_info, alias, qualified_module_name, compiler_input, node
        )
        self.namespace[alias] = module_info

    # load an InterfaceT or ModuleInfo from an import.
    # raises FileNotFoundError
    def _load_import(self, node: vy_ast.VyperNode, level: int, module_str: str, alias: str) -> Any:
        # the directory this (currently being analyzed) module is in
        self_search_path = Path(self.ast.resolved_path).parent

        with self.input_bundle.poke_search_path(self_search_path):
            return self._load_import_helper(node, level, module_str, alias)

    def _load_import_helper(
        self, node: vy_ast.VyperNode, level: int, module_str: str, alias: str
    ) -> tuple[CompilerInput, Any]:
        if _is_builtin(module_str):
            return _load_builtin_import(level, module_str)

        path = _import_to_path(level, module_str)

        # this could conceivably be in the ImportGraph but no need at this point
        if path in self._imported_modules:
            previous_import_stmt = self._imported_modules[path]
            raise DuplicateImport(f"{alias} imported more than once!", previous_import_stmt, node)

        self._imported_modules[path] = node

        err = None

        try:
            path_vy = path.with_suffix(".vy")
            file = self.input_bundle.load_file(path_vy)
            assert isinstance(file, FileInput)  # mypy hint

            module_ast = self._ast_from_file(file)

            with override_global_namespace(Namespace()):
                module_t = _analyze_module_r(
                    module_ast,
                    self.input_bundle,
                    import_graph=self._import_graph,
                    is_interface=False,
                )

                return file, ModuleInfo(module_t, alias)

        except FileNotFoundError as e:
            # escape `e` from the block scope, it can make things
            # easier to debug.
            err = e

        try:
            file = self.input_bundle.load_file(path.with_suffix(".vyi"))
            assert isinstance(file, FileInput)  # mypy hint
            module_ast = self._ast_from_file(file)

            with override_global_namespace(Namespace()):
                _analyze_module_r(
                    module_ast,
                    self.input_bundle,
                    import_graph=self._import_graph,
                    is_interface=True,
                )
                module_t = module_ast._metadata["type"]

                return file, module_t.interface

        except FileNotFoundError:
            pass

        try:
            file = self.input_bundle.load_file(path.with_suffix(".json"))
            assert isinstance(file, ABIInput)  # mypy hint
            return file, InterfaceT.from_json_abi(str(file.path), file.abi)
        except FileNotFoundError:
            pass

        hint = None
        if module_str.startswith("vyper.interfaces"):
            hint = "try renaming `vyper.interfaces` to `ethereum.ercs`"

        # copy search_paths, makes debugging a bit easier
        search_paths = self.input_bundle.search_paths.copy()  # noqa: F841
        raise ModuleNotFound(module_str, hint=hint) from err


def _parse_ast(file: FileInput) -> vy_ast.Module:
    module_path = file.resolved_path  # for error messages
    try:
        # try to get a relative path, to simplify the error message
        cwd = Path(".")
        if module_path.is_absolute():
            cwd = cwd.resolve()
        module_path = module_path.relative_to(cwd)
    except ValueError:
        # we couldn't get a relative path (cf. docs for Path.relative_to),
        # use the resolved path given to us by the InputBundle
        pass

    ret = vy_ast.parse_to_ast(
        file.source_code,
        source_id=file.source_id,
        module_path=module_path.as_posix(),
        resolved_path=file.resolved_path.as_posix(),
    )
    return ret


# convert an import to a path (without suffix)
def _import_to_path(level: int, module_str: str) -> PurePath:
    base_path = ""
    if level > 1:
        base_path = "../" * (level - 1)
    elif level == 1:
        base_path = "./"
    return PurePath(f"{base_path}{module_str.replace('.','/')}/")


# can add more, e.g. "vyper.builtins.interfaces", etc.
BUILTIN_PREFIXES = ["ethereum.ercs"]


# TODO: could move this to analysis/common.py or something
def _is_builtin(module_str):
    return any(module_str.startswith(prefix) for prefix in BUILTIN_PREFIXES)


_builtins_cache: dict[PathLike, tuple[CompilerInput, ModuleT]] = {}


def _load_builtin_import(level: int, module_str: str) -> tuple[CompilerInput, InterfaceT]:
    if not _is_builtin(module_str):  # pragma: nocover
        raise CompilerPanic("unreachable!")

    builtins_path = vyper.builtins.interfaces.__path__[0]
    # hygiene: convert to relpath to avoid leaking user directory info
    # (note Path.relative_to cannot handle absolute to relative path
    # conversion, so we must use the `os` module).
    builtins_path = os.path.relpath(builtins_path)

    search_path = Path(builtins_path).parent.parent.parent
    # generate an input bundle just because it knows how to build paths.
    input_bundle = FilesystemInputBundle([search_path])

    # remap builtins directory --
    # ethereum/ercs => vyper/builtins/interfaces
    remapped_module = module_str
    if remapped_module.startswith("ethereum.ercs"):
        remapped_module = remapped_module.removeprefix("ethereum.ercs")
        remapped_module = vyper.builtins.interfaces.__package__ + remapped_module

    path = _import_to_path(level, remapped_module).with_suffix(".vyi")

    # builtins are globally the same, so we can safely cache them
    # (it is also *correct* to cache them, so that types defined in builtins
    # compare correctly using pointer-equality.)
    if path in _builtins_cache:
        file, module_t = _builtins_cache[path]
        return file, module_t.interface

    try:
        file = input_bundle.load_file(path)
        assert isinstance(file, FileInput)  # mypy hint
    except FileNotFoundError as e:
        hint = None
        components = module_str.split(".")
        # common issue for upgrading codebases from v0.3.x to v0.4.x -
        # hint: rename ERC20 to IERC20
        if components[-1].startswith("ERC"):
            module_prefix = components[-1]
            hint = f"try renaming `{module_prefix}` to `I{module_prefix}`"
        raise ModuleNotFound(module_str, hint=hint) from e

    interface_ast = _parse_ast(file)

    with override_global_namespace(Namespace()):
        module_t = _analyze_module_r(interface_ast, input_bundle, ImportGraph(), is_interface=True)

    _builtins_cache[path] = file, module_t
    return file, module_t.interface

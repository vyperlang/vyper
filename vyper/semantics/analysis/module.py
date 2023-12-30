import os
from pathlib import Path, PurePath
from typing import Any, Optional

import vyper.builtins.interfaces
from vyper import ast as vy_ast
from vyper.ast.validation import validate_literal_nodes
from vyper.compiler.input_bundle import ABIInput, FileInput, FilesystemInputBundle, InputBundle
from vyper.evm.opcodes import version_check
from vyper.exceptions import (
    CallViolation,
    DuplicateImport,
    ExceptionList,
    InvalidLiteral,
    InvalidType,
    ModuleNotFound,
    NamespaceCollision,
    StateAccessViolation,
    StructureException,
    SyntaxException,
    VariableDeclarationException,
    VyperException,
)
from vyper.semantics.analysis.base import ImportInfo, Modifiability, ModuleInfo, VarInfo
from vyper.semantics.analysis.common import VyperNodeVisitorBase
from vyper.semantics.analysis.import_graph import ImportGraph
from vyper.semantics.analysis.local import ExprVisitor, validate_functions
from vyper.semantics.analysis.pre_typecheck import pre_typecheck
from vyper.semantics.analysis.utils import (
    check_modifiability,
    get_exact_type_from_node,
    validate_expected_type,
)
from vyper.semantics.data_locations import DataLocation
from vyper.semantics.namespace import Namespace, get_namespace, override_global_namespace
from vyper.semantics.types import EventT, FlagT, InterfaceT, StructT
from vyper.semantics.types.function import ContractFunctionT
from vyper.semantics.types.module import ModuleT
from vyper.semantics.types.utils import type_from_annotation


def validate_semantics(module_ast, input_bundle, is_interface=False) -> ModuleT:
    return validate_semantics_r(module_ast, input_bundle, ImportGraph(), is_interface)


def validate_semantics_r(
    module_ast: vy_ast.Module,
    input_bundle: InputBundle,
    import_graph: ImportGraph,
    is_interface: bool,
) -> ModuleT:
    """
    Analyze a Vyper module AST node, add all module-level objects to the
    namespace, type-check/validate semantics and annotate with type and analysis info
    """
    validate_literal_nodes(module_ast)

    pre_typecheck(module_ast)

    # validate semantics and annotate AST with type/semantics information
    namespace = get_namespace()

    with namespace.enter_scope(), import_graph.enter_path(module_ast):
        analyzer = ModuleAnalyzer(module_ast, input_bundle, namespace, import_graph, is_interface)
        ret = analyzer.analyze()

        vy_ast.expansion.generate_public_variable_getters(module_ast)

        # if this is an interface, the function is already validated
        # in `ContractFunction.from_vyi()`
        if not is_interface:
            validate_functions(module_ast)

    return ret


# compute reachable set and validate the call graph (detect cycles)
def _compute_reachable_set(fn_t: ContractFunctionT, path: list[ContractFunctionT] = None) -> None:
    path = path or []

    path.append(fn_t)
    root = path[0]

    for g in fn_t.called_functions:
        if g == root:
            message = " -> ".join([f.name for f in path])
            raise CallViolation(f"Contract contains cyclic function call: {message}")

        _compute_reachable_set(g, path=path)

        for h in g.reachable_internal_functions:
            assert h != fn_t  # sanity check

            fn_t.reachable_internal_functions.add(h)

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

        self.module_t: Optional[ModuleT] = None

        # ast cache, hitchhike onto the input_bundle object
        if not hasattr(self.input_bundle._cache, "_ast_of"):
            self.input_bundle._cache._ast_of: dict[int, vy_ast.Module] = {}  # type: ignore

    def analyze(self) -> ModuleT:
        # generate a `ModuleT` from the top-level node
        # note: also validates unique method ids
        if "type" in self.ast._metadata:
            assert isinstance(self.ast._metadata["type"], ModuleT)
            # we don't need to analyse again, skip out
            self.module_t = self.ast._metadata["type"]
            return self.module_t

        to_visit = self.ast.body.copy()

        # handle imports linearly
        # (do this instead of handling in the next block so that
        # `self._imported_modules` does not end up with garbage in it after
        # exception swallowing).
        import_stmts = self.ast.get_children((vy_ast.Import, vy_ast.ImportFrom))
        for node in import_stmts:
            self.visit(node)
            to_visit.remove(node)

        # keep trying to process all the nodes until we finish or can
        # no longer progress. this makes it so we don't need to
        # calculate a dependency tree between top-level items.
        while len(to_visit) > 0:
            count = len(to_visit)
            err_list = ExceptionList()
            for node in to_visit.copy():
                try:
                    self.visit(node)
                    to_visit.remove(node)
                except (InvalidLiteral, InvalidType, VariableDeclarationException) as e:
                    # these exceptions cannot be caused by another statement not yet being
                    # parsed, so we raise them immediately
                    raise e from None
                except VyperException as e:
                    err_list.append(e)

            # Only raise if no nodes were successfully processed. This allows module
            # level logic to parse regardless of the ordering of code elements.
            if count == len(to_visit):
                err_list.raise_if_not_empty()

        self.module_t = ModuleT(self.ast)
        self.ast._metadata["type"] = self.module_t

        # attach namespace to the module for downstream use.
        _ns = Namespace()
        # note that we don't just copy the namespace because
        # there are constructor issues.
        _ns.update({k: self.namespace[k] for k in self.namespace._scopes[-1]})  # type: ignore
        self.ast._metadata["namespace"] = _ns

        self.analyze_call_graph()

        return self.module_t

    def analyze_call_graph(self):
        # get list of internal function calls made by each function
        function_defs = self.module_t.function_defs

        for func in function_defs:
            fn_t = func._metadata["func_type"]

            function_calls = func.get_descendants(vy_ast.Call)

            for call in function_calls:
                try:
                    call_t = get_exact_type_from_node(call.func)
                except VyperException:
                    # either there is a problem getting the call type. this is
                    # an issue, but it will be handled properly later. right now
                    # we just want to be able to construct the call graph.
                    continue

                if isinstance(call_t, ContractFunctionT) and call_t.is_internal:
                    fn_t.called_functions.add(call_t)

        for func in function_defs:
            fn_t = func._metadata["func_type"]

            # compute reachable set and validate the call graph
            _compute_reachable_set(fn_t)

    def _ast_from_file(self, file: FileInput) -> vy_ast.Module:
        # cache ast if we have seen it before.
        # this gives us the additional property of object equality on
        # two ASTs produced from the same source
        ast_of = self.input_bundle._cache._ast_of
        if file.source_id not in ast_of:
            ast_of[file.source_id] = _parse_and_fold_ast(file)

        return ast_of[file.source_id]

    def visit_ImplementsDecl(self, node):
        type_ = type_from_annotation(node.annotation)

        if not isinstance(type_, InterfaceT):
            raise StructureException("Invalid interface name", node.annotation)

        type_.validate_implements(node)

    def visit_VariableDecl(self, node):
        name = node.get("target.id")
        if name is None:
            raise VariableDeclarationException("Invalid module-level assignment", node)

        if node.is_public:
            # generate function type and add to metadata
            # we need this when building the public getter
            node._metadata["getter_type"] = ContractFunctionT.getter_from_VariableDecl(node)

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
                raise SyntaxException(message, node.node_source_code, node.lineno, node.col_offset)

        data_loc = (
            DataLocation.CODE
            if node.is_immutable
            else DataLocation.UNSET
            if node.is_constant
            # XXX: needed if we want separate transient allocator
            # else DataLocation.TRANSIENT
            # if node.is_transient
            else DataLocation.STORAGE
        )

        modifiability = (
            Modifiability.IMMUTABLE
            if node.is_immutable
            else Modifiability.ALWAYS_CONSTANT
            if node.is_constant
            else Modifiability.MODIFIABLE
        )

        type_ = type_from_annotation(node.annotation, data_loc)

        if node.is_transient and not version_check(begin="cancun"):
            raise StructureException("`transient` is not available pre-cancun", node.annotation)

        var_info = VarInfo(
            type_,
            decl_node=node,
            location=data_loc,
            modifiability=modifiability,
            is_public=node.is_public,
            is_transient=node.is_transient,
        )
        node.target._metadata["varinfo"] = var_info  # TODO maybe put this in the global namespace
        node._metadata["type"] = type_

        def _finalize():
            # add the variable name to `self` namespace if the variable is either
            # 1. a public constant or immutable; or
            # 2. a storage variable, whether private or public
            if (node.is_constant or node.is_immutable) and not node.is_public:
                return

            try:
                self.namespace["self"].typ.add_member(name, var_info)
                node.target._metadata["type"] = type_
            except NamespaceCollision:
                # rewrite the error message to be slightly more helpful
                raise NamespaceCollision(
                    f"Value '{name}' has already been declared", node
                ) from None

        def _validate_self_namespace():
            # block globals if storage variable already exists
            if name in self.namespace["self"].typ.members:
                raise NamespaceCollision(
                    f"Value '{name}' has already been declared", node
                ) from None
            self.namespace[name] = var_info

        if node.is_constant:
            assert node.value is not None  # checked in VariableDecl.validate()

            ExprVisitor().visit(node.value, type_)

            if not check_modifiability(node.value, Modifiability.ALWAYS_CONSTANT):
                raise StateAccessViolation("Value must be a literal", node.value)

            validate_expected_type(node.value, type_)
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
        self.namespace[node.name] = obj

    def visit_EventDef(self, node):
        obj = EventT.from_EventDef(node)
        node._metadata["event_type"] = obj
        self.namespace[node.name] = obj

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

        self.namespace["self"].typ.add_member(func_t.name, func_t)
        node._metadata["func_type"] = func_t

    def visit_Import(self, node):
        # import x.y[name] as y[alias]

        alias = node.alias

        if alias is None:
            alias = node.name

        # don't handle things like `import x.y`
        if "." in alias:
            suggested_alias = node.name[node.name.rfind(".") :]
            suggestion = f"hint: try `import {node.name} as {suggested_alias}`"
            raise StructureException(
                f"import requires an accompanying `as` statement ({suggestion})", node
            )

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
        obj = InterfaceT.from_InterfaceDef(node)
        self.namespace[node.name] = obj

    def visit_StructDef(self, node):
        struct_t = StructT.from_StructDef(node)
        node._metadata["struct_type"] = struct_t
        self.namespace[node.name] = struct_t

    def _add_import(
        self, node: vy_ast.VyperNode, level: int, qualified_module_name: str, alias: str
    ) -> None:
        module_info = self._load_import(node, level, qualified_module_name, alias)
        node._metadata["import_info"] = ImportInfo(
            module_info, alias, qualified_module_name, self.input_bundle, node
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
    ) -> Any:
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
                module_t = validate_semantics_r(
                    module_ast,
                    self.input_bundle,
                    import_graph=self._import_graph,
                    is_interface=False,
                )

                return ModuleInfo(module_t)

        except FileNotFoundError as e:
            # escape `e` from the block scope, it can make things
            # easier to debug.
            err = e

        try:
            file = self.input_bundle.load_file(path.with_suffix(".vyi"))
            assert isinstance(file, FileInput)  # mypy hint
            module_ast = self._ast_from_file(file)

            with override_global_namespace(Namespace()):
                validate_semantics_r(
                    module_ast,
                    self.input_bundle,
                    import_graph=self._import_graph,
                    is_interface=True,
                )
                module_t = module_ast._metadata["type"]

                return module_t.interface

        except FileNotFoundError:
            pass

        try:
            file = self.input_bundle.load_file(path.with_suffix(".json"))
            assert isinstance(file, ABIInput)  # mypy hint
            return InterfaceT.from_json_abi(str(file.path), file.abi)
        except FileNotFoundError:
            pass

        # copy search_paths, makes debugging a bit easier
        search_paths = self.input_bundle.search_paths.copy()  # noqa: F841
        raise ModuleNotFound(module_str, node) from err


def _parse_and_fold_ast(file: FileInput) -> vy_ast.VyperNode:
    ret = vy_ast.parse_to_ast(
        file.source_code,
        source_id=file.source_id,
        module_path=str(file.path),
        resolved_path=str(file.resolved_path),
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
BUILTIN_PREFIXES = ["vyper.interfaces"]


def _is_builtin(module_str):
    return any(module_str.startswith(prefix) for prefix in BUILTIN_PREFIXES)


def _load_builtin_import(level: int, module_str: str) -> InterfaceT:
    if not _is_builtin(module_str):
        raise ModuleNotFoundError(f"Not a builtin: {module_str}") from None

    builtins_path = vyper.builtins.interfaces.__path__[0]
    # hygiene: convert to relpath to avoid leaking user directory info
    # (note Path.relative_to cannot handle absolute to relative path
    # conversion, so we must use the `os` module).
    builtins_path = os.path.relpath(builtins_path)

    search_path = Path(builtins_path).parent.parent.parent
    # generate an input bundle just because it knows how to build paths.
    input_bundle = FilesystemInputBundle([search_path])

    # remap builtins directory --
    # vyper/interfaces => vyper/builtins/interfaces
    remapped_module = module_str
    if remapped_module.startswith("vyper.interfaces"):
        remapped_module = remapped_module.removeprefix("vyper.interfaces")
        remapped_module = vyper.builtins.interfaces.__package__ + remapped_module

    path = _import_to_path(level, remapped_module).with_suffix(".vyi")

    try:
        file = input_bundle.load_file(path)
        assert isinstance(file, FileInput)  # mypy hint
    except FileNotFoundError:
        raise ModuleNotFoundError(f"Not a builtin: {module_str}") from None

    # TODO: it might be good to cache this computation
    interface_ast = _parse_and_fold_ast(file)

    with override_global_namespace(Namespace()):
        module_t = validate_semantics(interface_ast, input_bundle, is_interface=True)
    return module_t.interface

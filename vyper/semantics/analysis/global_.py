from collections import defaultdict

from vyper import ast as vy_ast
from vyper.exceptions import CompilerPanic, ExceptionList, InitializerException, StructureException
from vyper.semantics.analysis.base import InitializesInfo, UsesInfo
from vyper.semantics.types.base import TYPE_T, VyperType
from vyper.semantics.types.infinity import type_contains_unbounded_sequence
from vyper.semantics.types.module import ModuleT


def validate_compilation_target(module_t: ModuleT, experimental_codegen: bool = False) -> None:
    _validate_global_initializes_constraint(module_t)
    if not experimental_codegen:
        _validate_legacy_codegen_no_unbounded_sequences(module_t)


def _reject_legacy_unbounded_sequence(typ: VyperType, node: vy_ast.VyperNode) -> None:
    if type_contains_unbounded_sequence(typ):
        raise StructureException("unbounded sequence types require --experimental-codegen", node)


def _legacy_type_expression_from_node(node: vy_ast.VyperNode) -> VyperType | None:
    typ = getattr(node, "_metadata", {}).get("type")
    if isinstance(typ, TYPE_T):
        return typ.typedef

    expr_info = getattr(node, "_expr_info", None)
    typ = getattr(expr_info, "typ", None)
    if isinstance(typ, TYPE_T):
        return typ.typedef

    return None


def _validate_legacy_function_body_no_unbounded_sequences(func_t) -> None:
    assert func_t.ast_def is not None

    for stmt in func_t.ast_def.body:
        for node in stmt.get_descendants(vy_ast.ExprNode):
            typ = _legacy_type_expression_from_node(node)
            if typ is not None:
                _reject_legacy_unbounded_sequence(typ, node)


def _validate_legacy_codegen_no_unbounded_sequences(module_t: ModuleT) -> None:
    for var_info in module_t.variables.values():
        if var_info.is_constant:
            if var_info.decl_node is None:  # pragma: nocover
                raise CompilerPanic("constant missing declaration node")
            _reject_legacy_unbounded_sequence(var_info.typ, var_info.decl_node.annotation)

    for func_t in module_t.functions.values():
        for arg in func_t.arguments:
            if arg.ast_source is None:  # pragma: nocover
                raise CompilerPanic("function argument missing declaration node")
            _reject_legacy_unbounded_sequence(arg.typ, arg.ast_source.annotation)

        if func_t.return_type is not None:
            if func_t.ast_def is None:  # pragma: nocover
                raise CompilerPanic("function return type missing declaration node")
            _reject_legacy_unbounded_sequence(func_t.return_type, func_t.ast_def.returns)

        if func_t.ast_def is None:  # pragma: nocover
            raise CompilerPanic("function missing declaration node")
        for node in func_t.ast_def.get_descendants(vy_ast.AnnAssign):
            typ = node.target._metadata.get("type")
            if typ is None:  # pragma: nocover
                raise CompilerPanic("local variable missing analysis metadata")
            _reject_legacy_unbounded_sequence(typ, node.annotation)

        _validate_legacy_function_body_no_unbounded_sequences(func_t)


def _collect_used_modules_r(module_t):
    ret: defaultdict[ModuleT, list[UsesInfo]] = defaultdict(list)

    for uses_decl in module_t.uses_decls:
        for used_module in uses_decl._metadata["uses_info"].used_modules:
            ret[used_module.module_t].append(uses_decl)

            # recurse
            used_modules = _collect_used_modules_r(used_module.module_t)
            for k, v in used_modules.items():
                ret[k].extend(v)

    # also recurse into modules used by initialized modules
    for i in module_t.initialized_modules:
        used_modules = _collect_used_modules_r(i.module_info.module_t)
        for k, v in used_modules.items():
            ret[k].extend(v)

    return ret


def _collect_initialized_modules_r(module_t, seen=None):
    seen: dict[ModuleT, InitializesInfo] = seen or {}

    # list of InitializedInfo
    initialized_infos = module_t.initialized_modules

    for i in initialized_infos:
        initialized_module_t = i.module_info.module_t
        if initialized_module_t in seen:
            seen_nodes = (i.node, seen[initialized_module_t].node)
            raise InitializerException(f"`{i.module_info.alias}` initialized twice!", *seen_nodes)
        seen[initialized_module_t] = i

        _collect_initialized_modules_r(initialized_module_t, seen)

    return seen


# validate that each module which is `used` in the import graph is
# `initialized`.
def _validate_global_initializes_constraint(module_t: ModuleT):
    all_used_modules = _collect_used_modules_r(module_t)
    all_initialized_modules = _collect_initialized_modules_r(module_t)

    err_list = ExceptionList()

    for u, uses in all_used_modules.items():
        if u not in all_initialized_modules:
            msg = f"module `{u}` is used but never initialized!"

            # construct a hint if the module is in scope
            hint = None
            found_module = module_t.find_module_info(u)
            if found_module is not None:
                # TODO: do something about these constants
                if str(module_t) in ("<unknown>", "VyperContract.vy"):
                    module_str = "the top level of your main contract"
                else:
                    module_str = f"`{module_t}`"
                hint = f"add `initializes: {found_module.alias}` to {module_str}"

            err_list.append(InitializerException(msg, *uses, hint=hint))

    err_list.raise_if_not_empty()

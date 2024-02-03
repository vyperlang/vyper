from collections import defaultdict

from vyper.exceptions import ExceptionList, InitializerException
from vyper.semantics.analysis.base import InitializesInfo, UsesInfo
from vyper.semantics.analysis.import_graph import ImportGraph
from vyper.semantics.analysis.module import validate_module_semantics_r
from vyper.semantics.types.module import ModuleT


def validate_semantics(module_ast, input_bundle, is_interface=False) -> ModuleT:
    ret = validate_module_semantics_r(module_ast, input_bundle, ImportGraph(), is_interface)

    _validate_global_initializes_constraint(ret)

    return ret


def _collect_used_modules_r(module_t):
    ret: defaultdict[ModuleT, list[UsesInfo]] = defaultdict(list)

    for uses_decl in module_t.uses_decls:
        for used_module in uses_decl._metadata["uses_info"].used_modules:
            ret[used_module.module_t].append(uses_decl)

    for m_info in module_t.used_modules:
        used_modules = _collect_used_modules_r(m_info.module_t)
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
            err_list.append(
                InitializerException(
                    f"module {u} is used but never initialized!\n  "
                    f"(hint: add `initializes: module_name` to your main contract",
                    *uses,
                )
            )

    err_list.raise_if_not_empty()

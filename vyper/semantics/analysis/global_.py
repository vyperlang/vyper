from collections import defaultdict

from vyper.exceptions import ExceptionList, InitializerException
from vyper.semantics.analysis.base import InitializesInfo, UsesInfo
from vyper.semantics.types.module import ModuleT
from vyper.utils import OrderedSet


def validate_compilation_target(module_t: ModuleT):
    _validate_global_initializes_constraint(module_t)


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

    hint = None

    init_calls = []
    if module_t.init_function is not None:
        init_calls = list(module_t.init_function.reachable_internal_functions)
    seen: OrderedSet = OrderedSet()

    for init_t in init_calls:
        seen.add(init_t)
        init_m = init_t.decl_node.module_node._metadata["type"]
        init_info = all_initialized_modules[init_m]
        for dep in init_info.dependencies:
            m = dep.module_t
            if m.init_function is None:
                continue
            if m.init_function not in seen:
                # TODO: recover source info
                msg = f"Tried to initialize `{init_info.module_info.alias}`, "
                msg += f"but it depends on `{dep.alias}`, which has not been "
                msg += "initialized yet."
                hint = f"call `{dep.alias}.__init__()` before "
                hint += f"`{init_info.module_info.alias}.__init__()`."
                raise InitializerException(msg, hint=hint)

    err_list = ExceptionList()

    for u, uses in all_used_modules.items():
        if u not in all_initialized_modules:
            msg = f"module `{u}` is used but never initialized!"

            # construct a hint if the module is in scope
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

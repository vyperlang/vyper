from .. import types  # break a dependency cycle.


def __getattr__(name):
    if name == "validate_compilation_target":
        from .global_ import validate_compilation_target

        return validate_compilation_target
    if name == "analyze_module":
        from .module import analyze_module

        return analyze_module
    raise AttributeError(name)


__all__ = ["validate_compilation_target", "analyze_module"]

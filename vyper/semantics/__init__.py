def __getattr__(name):
    if name == "analyze_modules":
        from .analysis.module import analyze_modules

        return analyze_modules
    if name == "validate_compilation_target":
        from .analysis.global_ import validate_compilation_target

        return validate_compilation_target
    if name == "set_data_positions":
        from .analysis.data_positions import set_data_positions

        return set_data_positions
    raise AttributeError(name)

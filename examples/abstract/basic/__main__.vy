import override_module
import abstract_module
import caller_module

initializes: override_module
initializes: caller_module[abstract_module := abstract_module]

def use_a() -> uint256:
    return caller_module.use_a()

def use_o() -> String[9]:
    return override_module.bar("123456")

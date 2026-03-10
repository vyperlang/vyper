import override_module
import abstract_module

initializes: override_module
uses: abstract_module

def use_a() -> uint256:
    return abstract_module.foo(1)

def use_o() -> String[9]:
    return override_module.bar("123456")

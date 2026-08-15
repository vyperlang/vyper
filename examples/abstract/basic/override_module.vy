import abstract_module

initializes: abstract_module

@override(abstract_module)
def foo(x: uint256 = 0) -> uint256:
    return x + 1

@override(abstract_module)
def bar(y: String[6]) -> String[9]:
    return y

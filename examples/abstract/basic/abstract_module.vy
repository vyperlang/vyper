def regular() -> uint256:
    return self.foo(0)

@abstract
def foo(x: uint256) -> uint256:
    ...

@abstract
def bar(y: String[4]) -> String[10]:
    ...

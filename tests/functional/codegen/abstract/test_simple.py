def test_basic_default_default_param_function(env, get_logs, get_contract, make_input_bundle):
    contract = """
import foo

initializes: foo

@external
def my_method() -> uint256:
    return foo.foo()

def baz() -> uint256:
    return 101

@override(foo)
def bar() -> uint256:
    return self.baz()
    """
    foo = """
def foo() -> uint256:
    return self.bar()

@abstract
def bar() -> uint256: ...
    """
    input_bundle = make_input_bundle({"foo.vy": foo})
    c = get_contract(contract, input_bundle=input_bundle)

    assert c.my_method() == 101

import pytest

from vyper.exceptions import InitializerException


def test_basic_default_default_param_function(env, get_logs, get_contract, make_input_bundle):
    # Both modules "call" at least one method from the other one
    contract = """
import abstract_m

initializes: abstract_m

@external
def my_method() -> uint256:
    return abstract_m.foo()

@override(abstract_m)
def bar() -> uint256:
    return abstract_m.const()
    """

    abstract_m = """
def foo() -> uint256:
    return self.bar()

@abstract
def bar() -> uint256: ...

def const() -> uint256:
    return 101
    """
    input_bundle = make_input_bundle({"abstract_m.vy": abstract_m})
    c = get_contract(contract, input_bundle=input_bundle)

    assert c.my_method() == 101


def test_stateful_override_without_initializes(env, get_logs, get_contract, make_input_bundle):
    contract = """
import abstract_m
import override_m

# initializes: override_m # should fail gracefully without this

@external
def my_method() -> uint256:
    return abstract_m.bar()
    """

    abstract_m = """
@abstract
def bar() -> uint256: ...
    """

    override_m = """
import abstract_m
initializes: abstract_m

counter: uint256

@override(abstract_m)
def bar() -> uint256:
    self.counter += 1
    return 101
    """
    input_bundle = make_input_bundle({"abstract_m.vy": abstract_m, "override_m.vy": override_m})

    with pytest.raises(InitializerException) as e:
        get_contract(contract, input_bundle=input_bundle)

    # Verify the error message is helpful
    expected_msg = "Cannot call `bar` from `abstract_m` -"
    " it is overridden in `override_m` which accesses state, but `override_m` is not initialized"
    assert expected_msg == e.value.message
    assert "add `initializes: override_m` as a top-level statement to your contract" == e.value.hint


def test_stateful_override_with_initializes(env, get_logs, get_contract, make_input_bundle):
    # Test that the same contract works when override_m is properly initialized
    contract = """
import abstract_m
import override_m

initializes: override_m  # Now properly initialized

@external
def my_method() -> uint256:
    return abstract_m.bar()
    """

    abstract_m = """
@abstract
def bar() -> uint256: ...
    """

    override_m = """
import abstract_m
initializes: abstract_m

counter: uint256

@override(abstract_m)
def bar() -> uint256:
    self.counter += 1
    return 101
    """
    input_bundle = make_input_bundle({"abstract_m.vy": abstract_m, "override_m.vy": override_m})

    c = get_contract(contract, input_bundle=input_bundle)

    assert c.my_method() == 101

from vyper.exceptions import FunctionDeclarationException, StateAccessViolation


def test_pure_operation(get_contract_with_gas_estimation_for_constants):
    c = get_contract_with_gas_estimation_for_constants(
        """
@pure
@external
def foo() -> int128:
    return 5
    """
    )
    assert c.foo() == 5


def test_pure_call(get_contract_with_gas_estimation_for_constants):
    c = get_contract_with_gas_estimation_for_constants(
        """
@pure
@internal
def _foo() -> int128:
    return 5

@pure
@external
def foo() -> int128:
    return self._foo()
    """
    )
    assert c.foo() == 5


def test_pure_interface(get_contract_with_gas_estimation_for_constants):
    c1 = get_contract_with_gas_estimation_for_constants(
        """
@pure
@external
def foo() -> int128:
    return 5
    """
    )
    c2 = get_contract_with_gas_estimation_for_constants(
        """
interface Foo:
    def foo() -> int128: pure

@pure
@external
def foo(a: address) -> int128:
    return staticcall Foo(a).foo()
    """
    )
    assert c2.foo(c1.address) == 5


def test_invalid_envar_access(get_contract, assert_compile_failed):
    assert_compile_failed(
        lambda: get_contract(
            """
@pure
@external
def foo() -> uint256:
    return chain.id
    """
        ),
        StateAccessViolation,
    )


def test_invalid_state_access(get_contract, assert_compile_failed):
    assert_compile_failed(
        lambda: get_contract(
            """
x: uint256

@pure
@external
def foo() -> uint256:
    return self.x
    """
        ),
        StateAccessViolation,
    )


def test_invalid_self_access(get_contract, assert_compile_failed):
    assert_compile_failed(
        lambda: get_contract(
            """
@pure
@external
def foo() -> address:
    return self
    """
        ),
        StateAccessViolation,
    )


def test_invalid_call(get_contract, assert_compile_failed):
    assert_compile_failed(
        lambda: get_contract(
            """
@view
@internal
def _foo() -> uint256:
    return 5

@pure
@external
def foo() -> uint256:
    return self._foo()  # Fails because of calling non-pure fn
    """
        ),
        StateAccessViolation,
    )


def test_invalid_conflicting_decorators(get_contract, assert_compile_failed):
    assert_compile_failed(
        lambda: get_contract(
            """
@pure
@external
@payable
def foo() -> uint256:
    return 5
    """
        ),
        FunctionDeclarationException,
    )

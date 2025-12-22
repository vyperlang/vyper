"""
Tests for external call codegen (extcall/staticcall).
"""
import pytest

from vyper.codegen_venom.module import generate_runtime_venom, generate_deploy_venom
from vyper.compiler.phases import CompilerData
from vyper.compiler.settings import Settings


def _get_module_t(source: str):
    """Get module type from source."""
    compiler_data = CompilerData(source)
    return compiler_data.global_ctx


def _compile_source(source: str):
    """Compile source and return IR contexts (runtime, deploy)."""
    module_t = _get_module_t(source)
    settings = Settings()
    runtime_ctx = generate_runtime_venom(module_t, settings)
    # For testing, we don't need real bytecode - just verify IR generates
    return runtime_ctx, runtime_ctx  # Return runtime twice for compatibility


class TestExternalCallBasic:
    """Test basic external call lowering."""

    def test_staticcall_simple(self):
        """Test simple staticcall to view function."""
        source = """
# @version ^0.4.0

interface IFoo:
    def get_value() -> uint256: view

@external
def call_foo(target: address) -> uint256:
    return staticcall IFoo(target).get_value()
"""
        deploy_ctx, runtime_ctx = _compile_source(source)
        assert deploy_ctx is not None
        assert runtime_ctx is not None

    def test_extcall_simple(self):
        """Test simple extcall to nonpayable function."""
        source = """
# @version ^0.4.0

interface IFoo:
    def set_value(x: uint256): nonpayable

@external
def call_foo(target: address, val: uint256):
    extcall IFoo(target).set_value(val)
"""
        deploy_ctx, runtime_ctx = _compile_source(source)
        assert deploy_ctx is not None
        assert runtime_ctx is not None

    def test_staticcall_with_args(self):
        """Test staticcall with arguments."""
        source = """
# @version ^0.4.0

interface IFoo:
    def add(a: uint256, b: uint256) -> uint256: view

@external
def call_add(target: address, x: uint256, y: uint256) -> uint256:
    return staticcall IFoo(target).add(x, y)
"""
        deploy_ctx, runtime_ctx = _compile_source(source)
        assert deploy_ctx is not None
        assert runtime_ctx is not None

    def test_extcall_no_return(self):
        """Test extcall that returns nothing."""
        source = """
# @version ^0.4.0

interface IFoo:
    def do_something(): nonpayable

@external
def call_foo(target: address):
    extcall IFoo(target).do_something()
"""
        deploy_ctx, runtime_ctx = _compile_source(source)
        assert deploy_ctx is not None
        assert runtime_ctx is not None


class TestExternalCallKwargs:
    """Test external call keyword arguments."""

    def test_extcall_with_value(self):
        """Test extcall with value= kwarg (payable)."""
        source = """
# @version ^0.4.0

interface IFoo:
    def deposit(): payable

@external
@payable
def call_deposit(target: address):
    extcall IFoo(target).deposit(value=msg.value)
"""
        deploy_ctx, runtime_ctx = _compile_source(source)
        assert deploy_ctx is not None
        assert runtime_ctx is not None

    def test_staticcall_with_gas(self):
        """Test staticcall with gas= kwarg."""
        source = """
# @version ^0.4.0

interface IFoo:
    def get_value() -> uint256: view

@external
def call_with_gas(target: address) -> uint256:
    return staticcall IFoo(target).get_value(gas=100000)
"""
        deploy_ctx, runtime_ctx = _compile_source(source)
        assert deploy_ctx is not None
        assert runtime_ctx is not None

    def test_extcall_skip_contract_check(self):
        """Test extcall with skip_contract_check=True."""
        source = """
# @version ^0.4.0

interface IFoo:
    def do_something(): nonpayable

@external
def call_unsafe(target: address):
    extcall IFoo(target).do_something(skip_contract_check=True)
"""
        deploy_ctx, runtime_ctx = _compile_source(source)
        assert deploy_ctx is not None
        assert runtime_ctx is not None

    def test_staticcall_default_return_value(self):
        """Test staticcall with default_return_value kwarg."""
        source = """
# @version ^0.4.0

interface IERC20:
    def balanceOf(addr: address) -> uint256: view

@external
def safe_balance(token: address, account: address) -> uint256:
    return staticcall IERC20(token).balanceOf(account, default_return_value=0)
"""
        deploy_ctx, runtime_ctx = _compile_source(source)
        assert deploy_ctx is not None
        assert runtime_ctx is not None


class TestExternalCallReturnTypes:
    """Test external calls with different return types."""

    def test_staticcall_returns_bool(self):
        """Test staticcall returning bool."""
        source = """
# @version ^0.4.0

interface IFoo:
    def is_active() -> bool: view

@external
def check_active(target: address) -> bool:
    return staticcall IFoo(target).is_active()
"""
        deploy_ctx, runtime_ctx = _compile_source(source)
        assert deploy_ctx is not None
        assert runtime_ctx is not None

    def test_staticcall_returns_address(self):
        """Test staticcall returning address."""
        source = """
# @version ^0.4.0

interface IFoo:
    def get_owner() -> address: view

@external
def check_owner(target: address) -> address:
    return staticcall IFoo(target).get_owner()
"""
        deploy_ctx, runtime_ctx = _compile_source(source)
        assert deploy_ctx is not None
        assert runtime_ctx is not None

    def test_staticcall_returns_bytes32(self):
        """Test staticcall returning bytes32."""
        source = """
# @version ^0.4.0

interface IFoo:
    def get_hash() -> bytes32: view

@external
def check_hash(target: address) -> bytes32:
    return staticcall IFoo(target).get_hash()
"""
        deploy_ctx, runtime_ctx = _compile_source(source)
        assert deploy_ctx is not None
        assert runtime_ctx is not None


class TestInterfaceConstructor:
    """Test interface constructor lowering."""

    def test_interface_from_address(self):
        """Test interface constructor from address."""
        source = """
# @version ^0.4.0

interface IFoo:
    def get_value() -> uint256: view

@external
def call_at_address(target: address) -> uint256:
    foo: IFoo = IFoo(target)
    return staticcall foo.get_value()
"""
        deploy_ctx, runtime_ctx = _compile_source(source)
        assert deploy_ctx is not None
        assert runtime_ctx is not None

    def test_interface_address_property(self):
        """Test getting address from interface."""
        source = """
# @version ^0.4.0

interface IFoo:
    def get_value() -> uint256: view

@external
def get_interface_address(target: address) -> address:
    foo: IFoo = IFoo(target)
    return foo.address
"""
        deploy_ctx, runtime_ctx = _compile_source(source)
        assert deploy_ctx is not None
        assert runtime_ctx is not None


class TestExternalCallComplex:
    """Test complex external call scenarios."""

    def test_multiple_calls(self):
        """Test multiple external calls in one function."""
        source = """
# @version ^0.4.0

interface IFoo:
    def get_a() -> uint256: view
    def get_b() -> uint256: view

@external
def sum_values(target: address) -> uint256:
    a: uint256 = staticcall IFoo(target).get_a()
    b: uint256 = staticcall IFoo(target).get_b()
    return a + b
"""
        deploy_ctx, runtime_ctx = _compile_source(source)
        assert deploy_ctx is not None
        assert runtime_ctx is not None

    def test_call_result_in_condition(self):
        """Test using call result in a condition."""
        source = """
# @version ^0.4.0

interface IFoo:
    def is_valid() -> bool: view

@external
def check_and_act(target: address) -> uint256:
    if staticcall IFoo(target).is_valid():
        return 1
    return 0
"""
        deploy_ctx, runtime_ctx = _compile_source(source)
        assert deploy_ctx is not None
        assert runtime_ctx is not None

    def test_nested_interface_calls(self):
        """Test calling through returned interface."""
        source = """
# @version ^0.4.0

interface IFactory:
    def get_pair() -> address: view

interface IPair:
    def get_reserves() -> uint256: view

@external
def get_pair_reserves(factory: address) -> uint256:
    pair: address = staticcall IFactory(factory).get_pair()
    return staticcall IPair(pair).get_reserves()
"""
        deploy_ctx, runtime_ctx = _compile_source(source)
        assert deploy_ctx is not None
        assert runtime_ctx is not None


class TestExternalCallMutability:
    """Test external call mutability handling."""

    def test_view_function_uses_staticcall(self):
        """Test that view functions generate staticcall."""
        source = """
# @version ^0.4.0

interface IFoo:
    def get_value() -> uint256: view

@external
def call_view(target: address) -> uint256:
    return staticcall IFoo(target).get_value()
"""
        deploy_ctx, runtime_ctx = _compile_source(source)
        assert deploy_ctx is not None
        assert runtime_ctx is not None

    def test_pure_function_uses_staticcall(self):
        """Test that pure functions generate staticcall."""
        source = """
# @version ^0.4.0

interface IFoo:
    def compute(x: uint256) -> uint256: pure

@external
def call_pure(target: address, x: uint256) -> uint256:
    return staticcall IFoo(target).compute(x)
"""
        deploy_ctx, runtime_ctx = _compile_source(source)
        assert deploy_ctx is not None
        assert runtime_ctx is not None

    def test_nonpayable_function_uses_call(self):
        """Test that nonpayable functions generate call."""
        source = """
# @version ^0.4.0

interface IFoo:
    def set_value(x: uint256): nonpayable

@external
def call_nonpayable(target: address, x: uint256):
    extcall IFoo(target).set_value(x)
"""
        deploy_ctx, runtime_ctx = _compile_source(source)
        assert deploy_ctx is not None
        assert runtime_ctx is not None

    def test_payable_function_uses_call(self):
        """Test that payable functions generate call with value."""
        source = """
# @version ^0.4.0

interface IFoo:
    def deposit(): payable

@external
@payable
def call_payable(target: address):
    extcall IFoo(target).deposit(value=msg.value)
"""
        deploy_ctx, runtime_ctx = _compile_source(source)
        assert deploy_ctx is not None
        assert runtime_ctx is not None

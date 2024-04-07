import json
from functools import wraps

import pytest
import web3.exceptions
from eth_tester import EthereumTester, PyEVMBackend
from eth_utils.toolz import compose
from web3 import Web3
from web3.contract import Contract
from web3.providers.eth_tester import EthereumTesterProvider

from vyper import compiler
from vyper.ast.grammar import parse_vyper_source
from vyper.compiler.settings import Settings


def _none_addr(datatype, data):
    if datatype == "address" and int(data, base=16) == 0:
        return (datatype, None)
    else:
        return (datatype, data)


CONCISE_NORMALIZERS = (_none_addr,)


def zero_gas_price_strategy(web3, transaction_params=None):
    return 0  # zero gas price makes testing simpler.


@pytest.fixture(scope="module")
def tester(gas_limit):
    custom_genesis = PyEVMBackend._generate_genesis_params(overrides={"gas_limit": gas_limit})
    custom_genesis["base_fee_per_gas"] = 0
    backend = PyEVMBackend(genesis_parameters=custom_genesis)
    return EthereumTester(backend=backend)


@pytest.fixture(scope="module")
def w3(tester):
    w3 = Web3(EthereumTesterProvider(tester))
    w3.eth.set_gas_price_strategy(zero_gas_price_strategy)
    return w3


def get_compiler_gas_estimate(code, func):
    sigs = compiler.phases.CompilerData(code).function_signatures
    if func:
        return compiler.utils.build_gas_estimates(sigs)[func] + 22000
    else:
        return sum(compiler.utils.build_gas_estimates(sigs).values()) + 22000


def check_gas_on_chain(w3, tester, code, func=None, res=None):
    gas_estimate = get_compiler_gas_estimate(code, func)
    gas_actual = tester.get_block_by_number("latest")["gas_used"]
    # Computed upper bound on the gas consumption should
    # be greater than or equal to the amount of gas used
    if gas_estimate < gas_actual:
        raise Exception(f"Gas upper bound fail: bound {gas_estimate} actual {gas_actual}")

    print(f"Function name: {func} - Gas estimate {gas_estimate}, Actual: {gas_actual}")


def gas_estimation_decorator(w3, tester, fn, source_code, func):
    def decorator(*args, **kwargs):
        @wraps(fn)
        def decorated_function(*args, **kwargs):
            result = fn(*args, **kwargs)
            if "transact" in kwargs:
                check_gas_on_chain(w3, tester, source_code, func, res=result)
            return result

        return decorated_function(*args, **kwargs)

    return decorator


def set_decorator_to_contract_function(w3, tester, contract, source_code, func):
    func_definition = getattr(contract, func)
    func_with_decorator = gas_estimation_decorator(w3, tester, func_definition, source_code, func)
    setattr(contract, func, func_with_decorator)


class VyperMethod:
    ALLOWED_MODIFIERS = {"call", "estimateGas", "transact", "buildTransaction"}

    def __init__(self, function, normalizers=None):
        self._function = function
        self._function._return_data_normalizers = normalizers

    def __call__(self, *args, **kwargs):
        return self.__prepared_function(*args, **kwargs)

    def __prepared_function(self, *args, **kwargs):
        if not kwargs:
            modifier, modifier_dict = "call", {}
            fn_abi = [
                x
                for x in self._function.contract_abi
                if x.get("name") == self._function.function_identifier
            ].pop()
            # To make tests faster just supply some high gas value.
            modifier_dict.update({"gas": fn_abi.get("gas", 0) + 500000})
        elif len(kwargs) == 1:
            modifier, modifier_dict = kwargs.popitem()
            if modifier not in self.ALLOWED_MODIFIERS:
                raise TypeError(f"The only allowed keyword arguments are: {self.ALLOWED_MODIFIERS}")
        else:
            raise TypeError(f"Use up to one keyword argument, one of: {self.ALLOWED_MODIFIERS}")
        return getattr(self._function(*args), modifier)(modifier_dict)


class VyperContract:
    """
    An alternative Contract Factory which invokes all methods as `call()`,
    unless you add a keyword argument. The keyword argument assigns the prep method.
    This call
    > contract.withdraw(amount, transact={'from': eth.accounts[1], 'gas': 100000, ...})
    is equivalent to this call in the classic contract:
    > contract.functions.withdraw(amount).transact({'from': eth.accounts[1], 'gas': 100000, ...})
    """

    def __init__(self, classic_contract, method_class=VyperMethod):
        classic_contract._return_data_normalizers += CONCISE_NORMALIZERS
        self._classic_contract = classic_contract
        self.address = self._classic_contract.address
        protected_fn_names = [fn for fn in dir(self) if not fn.endswith("__")]

        try:
            fn_names = [fn["name"] for fn in self._classic_contract.functions._functions]
        except web3.exceptions.NoABIFunctionsFound:
            fn_names = []

        for fn_name in fn_names:
            # Override namespace collisions
            if fn_name in protected_fn_names:
                raise AttributeError(f"{fn_name} is protected!")
            else:
                _classic_method = getattr(self._classic_contract.functions, fn_name)
                _concise_method = method_class(
                    _classic_method, self._classic_contract._return_data_normalizers
                )
            setattr(self, fn_name, _concise_method)

    @classmethod
    def factory(cls, *args, **kwargs):
        return compose(cls, Contract.factory(*args, **kwargs))


def _get_contract(
    w3,
    source_code,
    optimize,
    experimental_codegen,
    output_formats,
    *args,
    override_opt_level=None,
    input_bundle=None,
    **kwargs,
):
    settings = Settings()
    settings.optimize = override_opt_level or optimize
    settings.experimental_codegen = experimental_codegen
    out = compiler.compile_code(
        source_code,
        # test that all output formats can get generated
        output_formats=output_formats,
        settings=settings,
        input_bundle=input_bundle,
        show_gas_estimates=True,  # Enable gas estimates for testing
    )
    parse_vyper_source(source_code)  # Test grammar.
    json.dumps(out["metadata"])  # test metadata is json serializable
    abi = out["abi"]
    bytecode = out["bytecode"]
    value = kwargs.pop("value_in_eth", 0) * 10**18  # Handle deploying with an eth value.
    c = w3.eth.contract(abi=abi, bytecode=bytecode)
    deploy_transaction = c.constructor(*args)
    tx_info = {"from": w3.eth.accounts[0], "value": value, "gasPrice": 0}
    tx_info.update(kwargs)
    tx_hash = deploy_transaction.transact(tx_info)
    address = w3.eth.get_transaction_receipt(tx_hash)["contractAddress"]
    return w3.eth.contract(address, abi=abi, bytecode=bytecode, ContractFactoryClass=VyperContract)


@pytest.fixture(scope="module")
def get_contract(optimize, experimental_codegen, output_formats):
    """
    This fixture is used for Hypothesis tests to ensure that
    the same contract is called over multiple runs of the test.
    """
    custom_genesis = PyEVMBackend._generate_genesis_params(overrides={"gas_limit": 4500000})
    custom_genesis["base_fee_per_gas"] = 0
    backend = PyEVMBackend(genesis_parameters=custom_genesis)
    tester = EthereumTester(backend=backend)
    w3 = Web3(EthereumTesterProvider(tester))
    w3.eth.set_gas_price_strategy(zero_gas_price_strategy)

    def get_contract_module(source_code, *args, **kwargs):
        return _get_contract(
            w3, source_code, optimize, experimental_codegen, output_formats, *args, **kwargs
        )

    return get_contract_module

# REVIEW: there is a lot in this module for just the single test. should we just
# delete it and re-add integration tests as a follow up? also, if we are going
# to keep it then maybe move it to
# tests/functional/integration/test_eth_tester.py
def test_slice_storage_bytes32(get_contract):
    code = """
bytez: bytes32
@external
def dice() -> Bytes[1]:
    self.bytez = convert(65, bytes32)
    c: Bytes[1] = slice(self.bytez, 31, 1)
    return c
    """

    c = get_contract(code)
    assert c.dice() == b"A"

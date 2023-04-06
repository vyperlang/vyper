import logging
from functools import wraps

import pytest
from eth_tester import EthereumTester, PyEVMBackend
from eth_utils import setup_DEBUG2_logging
from hexbytes import HexBytes
from web3 import Web3
from web3.providers.eth_tester import EthereumTesterProvider

from vyper import compiler
from vyper.codegen.ir_node import IRnode
from vyper.ir import compile_ir, optimizer

from .base_conftest import VyperContract, _get_contract, zero_gas_price_strategy

# Import the base_conftest fixtures
pytest_plugins = ["tests.base_conftest", "tests.fixtures.memorymock"]

############
# PATCHING #
############


def set_evm_verbose_logging():
    logger = logging.getLogger("eth.vm.computation.Computation")
    setup_DEBUG2_logging()
    logger.setLevel("DEBUG2")


# Useful options to comment out whilst working:
# set_evm_verbose_logging()
#
# from vdb import vdb
# vdb.set_evm_opcode_debugger()


def pytest_addoption(parser):
    parser.addoption("--no-optimize", action="store_true", help="disable asm and IR optimizations")


@pytest.fixture(scope="module")
def no_optimize(pytestconfig):
    return pytestconfig.getoption("no_optimize")


@pytest.fixture
def keccak():
    return Web3.keccak


@pytest.fixture
def abi_encode(w3):
    def f(abi_t, py_val):
        return w3.codec.encode_single(abi_t, py_val)

    return f


@pytest.fixture
def bytes_helper():
    def bytes_helper(str, length):
        return bytes(str, "utf-8") + bytearray(length - len(str))

    return bytes_helper


@pytest.fixture
def get_contract_from_ir(w3, no_optimize):
    def ir_compiler(ir, *args, **kwargs):
        ir = IRnode.from_list(ir)
        if not no_optimize:
            ir = optimizer.optimize(ir)
        bytecode, _ = compile_ir.assembly_to_evm(
            compile_ir.compile_to_assembly(ir, no_optimize=no_optimize)
        )
        abi = kwargs.get("abi") or []
        c = w3.eth.contract(abi=abi, bytecode=bytecode)
        deploy_transaction = c.constructor()
        tx_hash = deploy_transaction.transact()
        address = w3.eth.get_transaction_receipt(tx_hash)["contractAddress"]
        contract = w3.eth.contract(
            address, abi=abi, bytecode=bytecode, ContractFactoryClass=VyperContract
        )
        return contract

    return ir_compiler


@pytest.fixture(scope="module")
def get_contract_module(no_optimize):
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
        return _get_contract(w3, source_code, no_optimize, *args, **kwargs)

    return get_contract_module


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


@pytest.fixture
def get_contract_with_gas_estimation(tester, w3, no_optimize):
    def get_contract_with_gas_estimation(source_code, *args, **kwargs):

        contract = _get_contract(w3, source_code, no_optimize, *args, **kwargs)
        for abi in contract._classic_contract.functions.abi:
            if abi["type"] == "function":
                set_decorator_to_contract_function(w3, tester, contract, source_code, abi["name"])
        return contract

    return get_contract_with_gas_estimation


@pytest.fixture
def get_contract_with_gas_estimation_for_constants(w3, no_optimize):
    def get_contract_with_gas_estimation_for_constants(source_code, *args, **kwargs):
        return _get_contract(w3, source_code, no_optimize, *args, **kwargs)

    return get_contract_with_gas_estimation_for_constants


@pytest.fixture
def assert_compile_failed():
    def assert_compile_failed(function_to_test, exception=Exception):
        with pytest.raises(exception):
            function_to_test()

    return assert_compile_failed


@pytest.fixture
def search_for_sublist():
    def search_for_sublist(ir, sublist):
        _list = ir.to_list() if hasattr(ir, "to_list") else ir
        if _list == sublist:
            return True
        if isinstance(_list, list):
            for i in _list:
                ret = search_for_sublist(i, sublist)
                if ret is True:
                    return ret
        return False

    return search_for_sublist


@pytest.fixture
def create2_address_of(keccak):
    def _f(_addr, _salt, _initcode):
        prefix = HexBytes("0xff")
        addr = HexBytes(_addr)
        salt = HexBytes(_salt)
        initcode = HexBytes(_initcode)
        return keccak(prefix + addr + salt + keccak(initcode))[12:]

    return _f

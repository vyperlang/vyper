import json
import logging
from contextlib import contextmanager
from functools import wraps

import hypothesis
import pytest
import web3.exceptions
from eth_tester import EthereumTester, PyEVMBackend
from eth_tester.exceptions import TransactionFailed
from eth_utils import setup_DEBUG2_logging
from eth_utils.toolz import compose
from hexbytes import HexBytes
from web3 import Web3
from web3.contract import Contract
from web3.providers.eth_tester import EthereumTesterProvider

from tests.utils import working_directory
from vyper import compiler
from vyper.ast.grammar import parse_vyper_source
from vyper.codegen.ir_node import IRnode
from vyper.compiler.input_bundle import FilesystemInputBundle, InputBundle
from vyper.compiler.settings import OptimizationLevel, Settings, _set_debug_mode
from vyper.ir import compile_ir, optimizer
from vyper.utils import ERC5202_PREFIX

# Import the base fixtures
pytest_plugins = ["tests.fixtures.memorymock"]

############
# PATCHING #
############


# disable hypothesis deadline globally
hypothesis.settings.register_profile("ci", deadline=None)
hypothesis.settings.load_profile("ci")


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
    parser.addoption(
        "--optimize",
        choices=["codesize", "gas", "none"],
        default="gas",
        help="change optimization mode",
    )
    parser.addoption("--enable-compiler-debug-mode", action="store_true")


@pytest.fixture(scope="module")
def output_formats():
    output_formats = compiler.OUTPUT_FORMATS.copy()
    del output_formats["bb"]
    del output_formats["bb_runtime"]
    return output_formats


@pytest.fixture(scope="module")
def optimize(pytestconfig):
    flag = pytestconfig.getoption("optimize")
    return OptimizationLevel.from_string(flag)


@pytest.fixture(scope="session", autouse=True)
def debug(pytestconfig):
    debug = pytestconfig.getoption("enable_compiler_debug_mode")
    assert isinstance(debug, bool)
    _set_debug_mode(debug)


@pytest.fixture
def chdir_tmp_path(tmp_path):
    # this is useful for when you want imports to have relpaths
    with working_directory(tmp_path):
        yield


@pytest.fixture
def keccak():
    return Web3.keccak


@pytest.fixture
def make_file(tmp_path):
    # writes file_contents to file_name, creating it in the
    # tmp_path directory. returns final path.
    def fn(file_name, file_contents):
        path = tmp_path / file_name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w") as f:
            f.write(file_contents)

        return path

    return fn


# this can either be used for its side effects (to prepare a call
# to get_contract), or the result can be provided directly to
# compile_code / CompilerData.
@pytest.fixture
def make_input_bundle(tmp_path, make_file):
    def fn(sources_dict):
        for file_name, file_contents in sources_dict.items():
            make_file(file_name, file_contents)
        return FilesystemInputBundle([tmp_path])

    return fn


# for tests which just need an input bundle, doesn't matter what it is
@pytest.fixture
def dummy_input_bundle():
    return InputBundle([])


# TODO: remove me, this is just string.encode("utf-8").ljust()
# only used in test_logging.py.
@pytest.fixture
def bytes_helper():
    def bytes_helper(str, length):
        return bytes(str, "utf-8") + bytearray(length - len(str))

    return bytes_helper


def _none_addr(datatype, data):
    if datatype == "address" and int(data, base=16) == 0:
        return (datatype, None)
    else:
        return (datatype, data)


CONCISE_NORMALIZERS = (_none_addr,)


@pytest.fixture(scope="module")
def tester():
    # set absurdly high gas limit so that london basefee never adjusts
    # (note: 2**63 - 1 is max that evm allows)
    custom_genesis = PyEVMBackend._generate_genesis_params(overrides={"gas_limit": 10**10})
    custom_genesis["base_fee_per_gas"] = 0
    backend = PyEVMBackend(genesis_parameters=custom_genesis)
    return EthereumTester(backend=backend)


def zero_gas_price_strategy(web3, transaction_params=None):
    return 0  # zero gas price makes testing simpler.


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


@pytest.fixture
def get_contract_from_ir(w3, optimize):
    def ir_compiler(ir, *args, **kwargs):
        ir = IRnode.from_list(ir)
        if optimize != OptimizationLevel.NONE:
            ir = optimizer.optimize(ir)

        bytecode, _ = compile_ir.assembly_to_evm(
            compile_ir.compile_to_assembly(ir, optimize=optimize)
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


def _get_contract(
    w3,
    source_code,
    optimize,
    output_formats,
    *args,
    override_opt_level=None,
    input_bundle=None,
    **kwargs,
):
    settings = Settings()
    settings.evm_version = kwargs.pop("evm_version", None)
    settings.optimize = override_opt_level or optimize
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
def get_contract(w3, optimize, output_formats):
    def fn(source_code, *args, **kwargs):
        return _get_contract(w3, source_code, optimize, output_formats, *args, **kwargs)

    return fn


@pytest.fixture
def get_contract_with_gas_estimation(tester, w3, optimize, output_formats):
    def get_contract_with_gas_estimation(source_code, *args, **kwargs):
        contract = _get_contract(w3, source_code, optimize, output_formats, *args, **kwargs)
        for abi_ in contract._classic_contract.functions.abi:
            if abi_["type"] == "function":
                set_decorator_to_contract_function(w3, tester, contract, source_code, abi_["name"])
        return contract

    return get_contract_with_gas_estimation


@pytest.fixture
def get_contract_with_gas_estimation_for_constants(w3, optimize, output_formats):
    def get_contract_with_gas_estimation_for_constants(source_code, *args, **kwargs):
        return _get_contract(w3, source_code, optimize, output_formats, *args, **kwargs)

    return get_contract_with_gas_estimation_for_constants


@pytest.fixture(scope="module")
def get_contract_module(optimize, output_formats):
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
        return _get_contract(w3, source_code, optimize, output_formats, *args, **kwargs)

    return get_contract_module


def _deploy_blueprint_for(
    w3, source_code, optimize, output_formats, initcode_prefix=ERC5202_PREFIX, **kwargs
):
    settings = Settings()
    settings.evm_version = kwargs.pop("evm_version", None)
    settings.optimize = optimize
    out = compiler.compile_code(
        source_code,
        output_formats=output_formats,
        settings=settings,
        show_gas_estimates=True,  # Enable gas estimates for testing
    )
    parse_vyper_source(source_code)  # Test grammar.
    abi = out["abi"]
    bytecode = HexBytes(initcode_prefix) + HexBytes(out["bytecode"])
    bytecode_len = len(bytecode)
    bytecode_len_hex = hex(bytecode_len)[2:].rjust(4, "0")
    # prepend a quick deploy preamble
    deploy_preamble = HexBytes("61" + bytecode_len_hex + "3d81600a3d39f3")
    deploy_bytecode = HexBytes(deploy_preamble) + bytecode

    deployer_abi = []  # just a constructor
    c = w3.eth.contract(abi=deployer_abi, bytecode=deploy_bytecode)
    deploy_transaction = c.constructor()
    tx_info = {"from": w3.eth.accounts[0], "value": 0, "gasPrice": 0}

    tx_hash = deploy_transaction.transact(tx_info)
    address = w3.eth.get_transaction_receipt(tx_hash)["contractAddress"]

    # sanity check
    assert w3.eth.get_code(address) == bytecode, (w3.eth.get_code(address), bytecode)

    def factory(address):
        return w3.eth.contract(
            address, abi=abi, bytecode=bytecode, ContractFactoryClass=VyperContract
        )

    return w3.eth.contract(address, bytecode=deploy_bytecode), factory


@pytest.fixture(scope="module")
def deploy_blueprint_for(w3, optimize, output_formats):
    def deploy_blueprint_for(source_code, *args, **kwargs):
        return _deploy_blueprint_for(w3, source_code, optimize, output_formats, *args, **kwargs)

    return deploy_blueprint_for


# TODO: this should not be a fixture.
# remove me and replace all uses with `with pytest.raises`.
@pytest.fixture
def assert_compile_failed():
    def assert_compile_failed(function_to_test, exception=Exception):
        with pytest.raises(exception):
            function_to_test()

    return assert_compile_failed


@pytest.fixture
def create2_address_of(keccak):
    def _f(_addr, _salt, _initcode):
        prefix = HexBytes("0xff")
        addr = HexBytes(_addr)
        salt = HexBytes(_salt)
        initcode = HexBytes(_initcode)
        return keccak(prefix + addr + salt + keccak(initcode))[12:]

    return _f


@pytest.fixture
def side_effects_contract(get_contract):
    def generate(ret_type):
        """
        Generates a Vyper contract with an external `foo()` function, which
        returns the specified return value of the specified return type, for
        testing side effects using the `assert_side_effects_invoked` fixture.
        """
        code = f"""
counter: public(uint256)

@external
def foo(s: {ret_type}) -> {ret_type}:
    self.counter += 1
    return s
    """
        contract = get_contract(code)
        return contract

    return generate


@pytest.fixture
def assert_side_effects_invoked():
    def assert_side_effects_invoked(side_effects_contract, side_effects_trigger, n=1):
        start_value = side_effects_contract.counter()

        side_effects_trigger()

        end_value = side_effects_contract.counter()
        assert end_value == start_value + n

    return assert_side_effects_invoked


@pytest.fixture
def get_logs(w3):
    def get_logs(tx_hash, c, event_name):
        tx_receipt = w3.eth.get_transaction_receipt(tx_hash)
        return c._classic_contract.events[event_name]().process_receipt(tx_receipt)

    return get_logs


@pytest.fixture(scope="module")
def tx_failed(tester):
    @contextmanager
    def fn(exception=TransactionFailed, exc_text=None):
        snapshot_id = tester.take_snapshot()
        with pytest.raises(exception) as excinfo:
            yield excinfo
        tester.revert_to_snapshot(snapshot_id)
        if exc_text:
            # TODO test equality
            assert exc_text in str(excinfo.value), (exc_text, excinfo.value)

    return fn

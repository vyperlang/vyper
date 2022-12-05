import pytest
from eth_tester import EthereumTester, PyEVMBackend
from eth_tester.exceptions import TransactionFailed
from eth_utils.toolz import compose
from hexbytes import HexBytes
from web3 import Web3
from web3.contract import Contract, mk_collision_prop
from web3.providers.eth_tester import EthereumTesterProvider

from vyper import compiler
from vyper.ast.grammar import parse_vyper_source


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
            modifier_dict.update({"gas": fn_abi.get("gas", 0) + 50000})
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
        for fn_name in self._classic_contract.functions:
            # Override namespace collisions
            if fn_name in protected_fn_names:
                _concise_method = mk_collision_prop(fn_name)
            else:
                _classic_method = getattr(self._classic_contract.functions, fn_name)
                _concise_method = method_class(
                    _classic_method, self._classic_contract._return_data_normalizers
                )
            setattr(self, fn_name, _concise_method)

    @classmethod
    def factory(cls, *args, **kwargs):
        return compose(cls, Contract.factory(*args, **kwargs))


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
    custom_genesis = PyEVMBackend._generate_genesis_params(overrides={"gas_limit": 10 ** 10})
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


def _get_contract(w3, source_code, no_optimize, *args, **kwargs):
    out = compiler.compile_code(
        source_code,
        ["abi", "bytecode"],
        interface_codes=kwargs.pop("interface_codes", None),
        no_optimize=no_optimize,
        evm_version=kwargs.pop("evm_version", None),
        show_gas_estimates=True,  # Enable gas estimates for testing
    )
    parse_vyper_source(source_code)  # Test grammar.
    abi = out["abi"]
    bytecode = out["bytecode"]
    value = kwargs.pop("value_in_eth", 0) * 10 ** 18  # Handle deploying with an eth value.
    c = w3.eth.contract(abi=abi, bytecode=bytecode)
    deploy_transaction = c.constructor(*args)
    tx_info = {"from": w3.eth.accounts[0], "value": value, "gasPrice": 0}
    tx_info.update(kwargs)
    tx_hash = deploy_transaction.transact(tx_info)
    address = w3.eth.get_transaction_receipt(tx_hash)["contractAddress"]
    return w3.eth.contract(address, abi=abi, bytecode=bytecode, ContractFactoryClass=VyperContract)


def _deploy_blueprint_for(w3, source_code, no_optimize, initcode_prefix=b"", **kwargs):
    out = compiler.compile_code(
        source_code,
        ["abi", "bytecode"],
        interface_codes=kwargs.pop("interface_codes", None),
        no_optimize=no_optimize,
        evm_version=kwargs.pop("evm_version", None),
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
def deploy_blueprint_for(w3, no_optimize):
    def deploy_blueprint_for(source_code, *args, **kwargs):
        return _deploy_blueprint_for(w3, source_code, no_optimize, *args, **kwargs)

    return deploy_blueprint_for


@pytest.fixture(scope="module")
def get_contract(w3, no_optimize):
    def get_contract(source_code, *args, **kwargs):
        return _get_contract(w3, source_code, no_optimize, *args, **kwargs)

    return get_contract


@pytest.fixture
def get_logs(w3):
    def get_logs(tx_hash, c, event_name):
        tx_receipt = w3.eth.get_transaction_receipt(tx_hash)
        return c._classic_contract.events[event_name]().processReceipt(tx_receipt)

    return get_logs


@pytest.fixture(scope="module")
def assert_tx_failed(tester):
    def assert_tx_failed(function_to_test, exception=TransactionFailed, exc_text=None):
        snapshot_id = tester.take_snapshot()
        with pytest.raises(exception) as excinfo:
            function_to_test()
        tester.revert_to_snapshot(snapshot_id)
        if exc_text:
            # TODO test equality
            assert exc_text in str(excinfo.value), (exc_text, excinfo.value)

    return assert_tx_failed

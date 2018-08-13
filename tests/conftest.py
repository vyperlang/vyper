import eth_tester
import logging
import pytest
import web3

from functools import wraps

from eth_tester import (
    EthereumTester,
)
from eth_tester.exceptions import (
    TransactionFailed
)
from web3.providers.eth_tester import (
    EthereumTesterProvider,
)

from web3 import (
    Web3,
)
from web3.contract import (
    ConciseContract,
    ConciseMethod
)
from vyper.parser.parser_utils import (
    LLLnode
)
from vyper import (
    compile_lll,
    compiler,
    optimizer,
)


class VyperMethod(ConciseMethod):
    ALLOWED_MODIFIERS = {'call', 'estimateGas', 'transact', 'buildTransaction'}

    def __call__(self, *args, **kwargs):
        return self.__prepared_function(*args, **kwargs)

    def __prepared_function(self, *args, **kwargs):
        if not kwargs:
            modifier, modifier_dict = 'call', {}
            fn_abi = [x for x in self._function.contract_abi if x['name'] == self._function.function_identifier].pop()
            modifier_dict.update({'gas': fn_abi.get('gas', 0) + 50000})  # To make tests faster just supply some high gas value.
        elif len(kwargs) == 1:
            modifier, modifier_dict = kwargs.popitem()
            if modifier not in self.ALLOWED_MODIFIERS:
                raise TypeError(
                    "The only allowed keyword arguments are: %s" % self.ALLOWED_MODIFIERS)
        else:
            raise TypeError("Use up to one keyword argument, one of: %s" % self.ALLOWED_MODIFIERS)

        return getattr(self._function(*args), modifier)(modifier_dict)


class VyperContract(ConciseContract):

    def __init__(self, classic_contract, method_class=VyperMethod):
        super().__init__(classic_contract, method_class)


############
# PATCHING #
############

setattr(eth_tester.backends.pyevm.main, 'GENESIS_GAS_LIMIT', 10**9)
setattr(eth_tester.backends.pyevm.main, 'GENESIS_DIFFICULTY', 1)


def set_evm_verbose_logging():
    logger = logging.getLogger('evm')
    logger.setLevel('TRACE')


# Useful options to comment out whilst working:
# set_evm_verbose_logging()
# vdb.set_evm_opcode_debugger()


@pytest.fixture(autouse=True)
def patch_log_filter_remove(monkeypatch):

    def Filter_remove(self, *values):

        def get_key(v):
            return v.get('transaction_hash'), v.get('log_index'), v.get('transaction_index')

        values_to_remove = set([
            get_key(value)
            for value in values
        ])

        queued_values = self.get_changes()
        self.values = [
            value
            for value
            in self.get_all()
            if get_key(value) not in values_to_remove
        ]
        for value in queued_values:
            if get_key(value) in values_to_remove:
                continue
            self.queue.put_nowait(value)

    monkeypatch.setattr(eth_tester.utils.filters.Filter, 'remove', Filter_remove)


@pytest.fixture(autouse=True)
def patch_is_encodeable_for_fixed(monkeypatch):
    original_is_encodable = web3.utils.abi.is_encodable

    def utils_abi_is_encodable(_type, value):
        from eth_utils import is_integer
        from eth_abi.abi import process_type
        try:
            base, sub, arrlist = _type
        except ValueError:
            base, sub, arrlist = process_type(_type)

        if not arrlist:
            if base == 'fixed' and not arrlist:
                return True
            elif base == 'int':
                if not is_integer(value):
                    return False
                exp = int(sub)
                if value < -1 * 2**(exp - 1) or value > 2**(exp - 1) + 1:
                    return False
                return True

        # default behaviour
        return original_is_encodable(_type, value)

    monkeypatch.setattr(web3.utils.abi, 'is_encodable', utils_abi_is_encodable)


@pytest.fixture(scope="module")
def tester():
    t = EthereumTester()
    return t


def zero_gas_price_strategy(web3, transaction_params=None):
    return 0  # zero gas price makes testing simpler.


@pytest.fixture(scope="module")
def w3(tester):
    w3 = Web3(EthereumTesterProvider(tester))
    w3.eth.setGasPriceStrategy(zero_gas_price_strategy)
    return w3


@pytest.fixture
def keccak():
    return Web3.sha3


@pytest.fixture
def bytes_helper():
    def bytes_helper(str, length):
        return bytes(str, 'utf-8') + bytearray(length - len(str))
    return bytes_helper


@pytest.fixture
def get_contract_from_lll(w3):
    def lll_compiler(lll, *args, **kwargs):
        lll = optimizer.optimize(LLLnode.from_list(lll))
        bytecode = compile_lll.assembly_to_evm(compile_lll.compile_to_assembly(lll))
        abi = kwargs.get('abi') or []
        contract = w3.eth.contract(bytecode=bytecode, abi=abi)
        deploy_transaction = {
            'data': contract._encode_constructor_data(args, kwargs)
        }
        tx = w3.eth.sendTransaction(deploy_transaction)
        address = w3.eth.getTransactionReceipt(tx)['contractAddress']
        contract = w3.eth.contract(address, abi=abi, bytecode=bytecode, ContractFactoryClass=VyperContract)
        return contract
    return lll_compiler


def _get_contract(w3, source_code, *args, **kwargs):
    abi = compiler.mk_full_signature(source_code)
    bytecode = '0x' + compiler.compile(source_code).hex()
    contract = w3.eth.contract(abi=abi, bytecode=bytecode)

    value = kwargs.pop('value', 0)
    value_in_eth = kwargs.pop('value_in_eth', 0)
    value = value_in_eth * 10**18 if value_in_eth else value  # Handle deploying with an eth value.
    gasPrice = kwargs.pop('gasPrice', 0)
    deploy_transaction = {
        'from': w3.eth.accounts[0],
        'data': contract._encode_constructor_data(args, kwargs),
        'value': value,
        'gasPrice': gasPrice,
    }
    tx = w3.eth.sendTransaction(deploy_transaction)
    address = w3.eth.getTransactionReceipt(tx)['contractAddress']
    contract = w3.eth.contract(address, abi=abi, bytecode=bytecode, ContractFactoryClass=VyperContract)
    # Filter logs.
    contract._logfilter = w3.eth.filter({
        'fromBlock': w3.eth.blockNumber - 1,
        'address': contract.address
    })
    return contract


@pytest.fixture
def get_contract(w3):
    def get_contract(source_code, *args, **kwargs):
        return _get_contract(w3, source_code, *args, **kwargs)
    return get_contract


def get_compiler_gas_estimate(code, func):
    if func:
        return compiler.gas_estimate(code)[func] + 22000
    else:
        return sum(compiler.gas_estimate(code).values()) + 22000


def check_gas_on_chain(w3, tester, code, func=None, res=None):
    gas_estimate = get_compiler_gas_estimate(code, func)
    gas_actual = tester.get_block_by_number('latest')['gas_used']
    # Computed upper bound on the gas consumption should
    # be greater than or equal to the amount of gas used
    if gas_estimate < gas_actual:
        raise Exception("Gas upper bound fail: bound %d actual %d" % (gas_estimate, gas_actual))

    print('Function name: {} - Gas estimate {}, Actual: {}'.format(
        func, gas_estimate, gas_actual)
    )


def gas_estimation_decorator(w3, tester, fn, source_code, func):
    def decorator(*args, **kwargs):
        @wraps(fn)
        def decorated_function(*args, **kwargs):
            result = fn(*args, **kwargs)
            if 'transact' in kwargs:
                check_gas_on_chain(w3, tester, source_code, func, res=result)
            return result
        return decorated_function(*args, **kwargs)
    return decorator


def set_decorator_to_contract_function(w3, tester, contract, source_code, func):
    func_definition = getattr(contract, func)
    func_with_decorator = gas_estimation_decorator(
        w3, tester, func_definition, source_code, func
    )
    setattr(contract, func, func_with_decorator)


@pytest.fixture
def get_contract_with_gas_estimation(tester, w3):
    def get_contract_with_gas_estimation(source_code, *args, **kwargs):

        contract = _get_contract(w3, source_code, *args, **kwargs)
        for abi in contract._classic_contract.functions.abi:
            if abi['type'] == 'function':
                set_decorator_to_contract_function(
                    w3, tester, contract, source_code, abi['name']
                )
        return contract
    return get_contract_with_gas_estimation


@pytest.fixture
def get_contract_with_gas_estimation_for_constants(w3):
    def get_contract_with_gas_estimation_for_constants(
            source_code,
            *args, **kwargs):
        return _get_contract(w3, source_code, *args, **kwargs)
    return get_contract_with_gas_estimation_for_constants


@pytest.fixture
def assert_tx_failed(tester):
    def assert_tx_failed(function_to_test, exception=TransactionFailed):
        snapshot_id = tester.take_snapshot()
        with pytest.raises(exception):
            function_to_test()
        tester.revert_to_snapshot(snapshot_id)
    return assert_tx_failed


@pytest.fixture
def assert_compile_failed():
    def assert_compile_failed(function_to_test, exception=Exception):
        with pytest.raises(exception):
            function_to_test()
    return assert_compile_failed


@pytest.fixture
def get_logs(w3):
    def get_logs(tx_hash, c, event_name):
        tx_receipt = w3.eth.getTransactionReceipt(tx_hash)
        logs = c._classic_contract.events[event_name]().processReceipt(tx_receipt)
        return logs
    return get_logs

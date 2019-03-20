from functools import (
    wraps,
)
import logging

from eth_tester import (
    EthereumTester,
)
from eth_tester.exceptions import (
    TransactionFailed,
)
import pytest
from web3 import Web3
from web3._utils.toolz import (
    compose,
)
from web3.contract import (
    Contract,
    mk_collision_prop,
)
from web3.providers.eth_tester import (
    EthereumTesterProvider,
)

from vyper import (
    compile_lll,
    compiler,
    optimizer,
)
from vyper.parser.parser_utils import (
    LLLnode,
)


class VyperMethod:
    ALLOWED_MODIFIERS = {'call', 'estimateGas', 'transact', 'buildTransaction'}

    def __init__(self, function, normalizers=None):
        self._function = function
        self._function._return_data_normalizers = normalizers

    def __call__(self, *args, **kwargs):
        return self.__prepared_function(*args, **kwargs)

    def __prepared_function(self, *args, **kwargs):
        if not kwargs:
            modifier, modifier_dict = 'call', {}
            fn_abi = [
                x
                for x
                in self._function.contract_abi
                if x.get('name') == self._function.function_identifier
            ].pop()
            # To make tests faster just supply some high gas value.
            modifier_dict.update({'gas': fn_abi.get('gas', 0) + 50000})
        elif len(kwargs) == 1:
            modifier, modifier_dict = kwargs.popitem()
            if modifier not in self.ALLOWED_MODIFIERS:
                raise TypeError(
                    "The only allowed keyword arguments are: %s" % self.ALLOWED_MODIFIERS)
        else:
            raise TypeError("Use up to one keyword argument, one of: %s" % self.ALLOWED_MODIFIERS)

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

        protected_fn_names = [fn for fn in dir(self) if not fn.endswith('__')]

        for fn_name in self._classic_contract.functions:

            # Override namespace collisions
            if fn_name in protected_fn_names:
                _concise_method = mk_collision_prop(fn_name)

            else:
                _classic_method = getattr(
                    self._classic_contract.functions,
                    fn_name)

                _concise_method = method_class(
                    _classic_method,
                    self._classic_contract._return_data_normalizers
                )

            setattr(self, fn_name, _concise_method)

    @classmethod
    def factory(cls, *args, **kwargs):
        return compose(cls, Contract.factory(*args, **kwargs))


def _none_addr(datatype, data):
    if datatype == 'address' and int(data, base=16) == 0:
        return (datatype, None)
    else:
        return (datatype, data)


CONCISE_NORMALIZERS = (
    _none_addr,
)

############
# PATCHING #
############

# setattr(eth_tester.backends.pyevm.main, 'GENESIS_GAS_LIMIT', 10**9)
# setattr(eth_tester.backends.pyevm.main, 'GENESIS_DIFFICULTY', 1)


def set_evm_verbose_logging():
    logger = logging.getLogger('evm')
    logger.setLevel('TRACE')


# Useful options to comment out whilst working:
# set_evm_verbose_logging()
# from vdb import vdb
# vdb.set_evm_opcode_debugger()


@pytest.fixture
def tester():
    t = EthereumTester()
    return t


def zero_gas_price_strategy(web3, transaction_params=None):
    return 0  # zero gas price makes testing simpler.


@pytest.fixture
def w3(tester):
    w3 = Web3(EthereumTesterProvider(tester))
    w3.eth.setGasPriceStrategy(zero_gas_price_strategy)
    return w3


@pytest.fixture
def keccak():
    return Web3.keccak


@pytest.fixture
def bytes_helper():
    def bytes_helper(str, length):
        return bytes(str, 'utf-8') + bytearray(length - len(str))
    return bytes_helper


@pytest.fixture
def get_contract_from_lll(w3):
    def lll_compiler(lll, *args, **kwargs):
        lll = optimizer.optimize(LLLnode.from_list(lll))
        bytecode, _ = compile_lll.assembly_to_evm(compile_lll.compile_to_assembly(lll))
        abi = kwargs.get('abi') or []
        contract = w3.eth.contract(bytecode=bytecode, abi=abi)
        deploy_transaction = {
            'data': contract._encode_constructor_data(args, kwargs)
        }
        tx = w3.eth.sendTransaction(deploy_transaction)
        address = w3.eth.getTransactionReceipt(tx)['contractAddress']
        contract = w3.eth.contract(
            address,
            abi=abi,
            bytecode=bytecode,
            ContractFactoryClass=VyperContract,
        )
        return contract
    return lll_compiler


def _get_contract(w3, source_code, *args, **kwargs):
    out = compiler.compile_code(
        source_code,
        ['abi', 'bytecode'],
        interface_codes=kwargs.pop('interface_codes', None),
    )
    abi = out['abi']
    bytecode = out['bytecode']
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
    contract = w3.eth.contract(
        address,
        abi=abi,
        bytecode=bytecode,
        ContractFactoryClass=VyperContract,
    )
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


@pytest.fixture(scope='module')
def get_contract_module():
    tester = EthereumTester()
    w3 = Web3(EthereumTesterProvider(tester))
    w3.eth.setGasPriceStrategy(zero_gas_price_strategy)

    def get_contract_module(source_code, *args, **kwargs):
        return _get_contract(w3, source_code, *args, **kwargs)

    return get_contract_module


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


@pytest.fixture
def search_for_sublist():

    def search_for_sublist(lll, sublist):
        _list = lll.to_list() if hasattr(lll, 'to_list') else lll
        if _list == sublist:
            return True
        if isinstance(_list, list):
            for i in _list:
                ret = search_for_sublist(i, sublist)
                if ret is True:
                    return ret
        return False

    return search_for_sublist

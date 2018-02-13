import pytest
from functools import wraps

from ethereum.tools import tester
from vyper.parser.parser_utils import (
    LLLnode
)
from vyper import (
    compile_lll,
    optimizer,
    compiler,
)
from ethereum import utils as ethereum_utils


@pytest.fixture
def check_gas(chain):
    def check_gas(code, func=None, num_txs=1):
        if func:
            gas_estimate = tester.languages['vyper'].gas_estimate(code)[func]
        else:
            gas_estimate = sum(tester.languages['vyper'].gas_estimate(code).values())
        gas_actual = chain.head_state.receipts[-1].gas_used \
                     - chain.head_state.receipts[-1 - num_txs].gas_used \
                     - chain.last_tx.intrinsic_gas_used * num_txs

        # Computed upper bound on the gas consumption should
        # be greater than or equal to the amount of gas used
        if gas_estimate < gas_actual:
            raise Exception("Gas upper bound fail: bound %d actual %d" % (gas_estimate, gas_actual))

        print('Function name: {} - Gas estimate {}, Actual: {}'.format(
            func, gas_estimate, gas_actual)
        )
    return check_gas


def gas_estimation_decorator(chain, fn, source_code, func):
    def decorator(*args, **kwargs):
        @wraps(fn)
        def decorated_function(*args, **kwargs):
            result = fn(*args, **kwargs)
            check_gas(chain)(source_code, func)
            return result
        return decorated_function(*args, **kwargs)
    return decorator


def set_decorator_to_contract_function(chain, contract, source_code, func):
    func_definition = getattr(contract, func)
    func_with_decorator = gas_estimation_decorator(
        chain, func_definition, source_code, func
    )
    setattr(contract, func, func_with_decorator)


@pytest.fixture
def bytes_helper():
    def bytes_helper(str, length):
        return bytes(str, 'utf-8') + bytearray(length - len(str))
    return bytes_helper


@pytest.fixture
def t():
    tester.s = tester.Chain()
    return tester


@pytest.fixture(scope="module")
def chain():
    tester.languages['vyper'] = compiler.Compiler()
    s = tester.Chain()
    s.head_state.gas_limit = 10**9
    return s


@pytest.fixture
def utils():
    return ethereum_utils


@pytest.fixture
def get_contract_from_lll(t):
    def lll_compiler(lll):
        lll = optimizer.optimize(LLLnode.from_list(lll))
        byte_code = compile_lll.assembly_to_evm(compile_lll.compile_to_assembly(lll))
        t.s.tx(to=b'', data=byte_code)
    return lll_compiler


@pytest.fixture
def get_contract_with_gas_estimation(chain):
    def get_contract_with_gas_estimation(
            source_code,
            *args, **kwargs):
        contract = chain.contract(source_code, language="vyper", *args, **kwargs)
        for func_name in contract.translator.function_data:
            set_decorator_to_contract_function(
                chain, contract, source_code, func_name
            )
        return contract

    return get_contract_with_gas_estimation


@pytest.fixture
def get_contract_with_gas_estimation_for_constants(chain):
    def get_contract_with_gas_estimation_for_constants(
            source_code,
            *args, **kwargs):
        abi = tester.languages['vyper'].mk_full_signature(source_code)
        # Take out constants from the abi for the purpose of gas estimation
        for func in abi:
            func['constant'] = False
        ct = tester.ContractTranslator(abi)
        byte_code = tester.languages['vyper'].compile(source_code) + (ct.encode_constructor_arguments(kwargs['args']) if kwargs else b'')
        address = chain.tx(to=b'', data=byte_code)
        contract = tester.ABIContract(chain, abi, address)
        for func_name in contract.translator.function_data:
            set_decorator_to_contract_function(
                chain, contract, source_code, func_name
            )
        return contract
    return get_contract_with_gas_estimation_for_constants


@pytest.fixture
def get_contract(chain):
    def get_contract(source_code, *args, **kwargs):
        return chain.contract(source_code, language="vyper", *args, **kwargs)
    return get_contract


@pytest.fixture
def assert_tx_failed(t):
    def assert_tx_failed(function_to_test, exception=tester.TransactionFailed):
        initial_state = t.s.snapshot()
        with pytest.raises(exception):
            function_to_test()
        t.s.revert(initial_state)
    return assert_tx_failed


@pytest.fixture
def assert_compile_failed(get_contract_from_lll):
    def assert_compile_failed(function_to_test, exception=tester.TransactionFailed):
        with pytest.raises(exception):
            function_to_test()
    return assert_compile_failed


@pytest.fixture
def get_logs():
    def get_logs(receipt, contract, event_name=None):
        contract_log_ids = contract.translator.event_data.keys()  # All the log ids contract has
        # All logs originating from contract, and matching event_name (if specified)
        logs = [log for log in receipt.logs
                if log.topics[0] in contract_log_ids and
                log.address == contract.address and
                (not event_name or
                 contract.translator.event_data[log.topics[0]]['name'] == event_name)]
        assert len(logs) > 0, "No logs in last receipt"

        # Return all events decoded in the receipt
        return [contract.translator.decode_event(log.topics, log.data) for log in logs]
    return get_logs


@pytest.fixture
def get_last_log(get_logs):
    def get_last_log(tester, contract, event_name=None):
        receipt = tester.s.head_state.receipts[-1]  # Only the receipts for the last block
        # Get last log event with correct name and return the decoded event
        print(get_logs(receipt, contract, event_name=event_name))
        return get_logs(receipt, contract, event_name=event_name)[-1]
    return get_last_log

import pytest
from functools import wraps

from viper import parser, compile_lll, utils
from viper import compiler
from ethereum.tools import tester
from ethereum import transactions, messages
from ethereum import utils as ethereum_utils
import rlp
from ethereum.slogging import LogRecorder, configure_logging, set_level
config_string = ':info,eth.vm.log:trace,eth.vm.op:trace,eth.vm.stack:trace,eth.vm.exit:trace,eth.pb.msg:trace,eth.pb.tx:debug'
#configure_logging(config_string=config_string)

chain = tester.Chain()
tester.languages['viper'] = compiler.Compiler() 

def inject_tx(txhex):
    tx = rlp.decode(ethereum_utils.decode_hex(txhex[2:]), transactions.Transaction)
    chain.head_state.set_balance(tx.sender, tx.startgas * tx.gasprice)
    chain.chain.state.set_balance(tx.sender, tx.startgas * tx.gasprice)
    messages.apply_transaction(chain.head_state, tx)
    chain.block.transactions.append(tx)
    contract_address = ethereum_utils.sha3(rlp.encode([tx.sender, 0]))[12:]
    assert chain.head_state.get_code(contract_address)
    chain.mine(1)
    return contract_address

_rlp_decoder_address = inject_tx("0xf9035b808506fc23ac0083045ef88080b903486103305660006109ac5260006109cc527f0100000000000000000000000000000000000000000000000000000000000000600035046109ec526000610a0c5260006109005260c06109ec51101515585760f86109ec51101561006e5760bf6109ec510336141558576001610a0c52610098565b60013560f76109ec51036020035260005160f66109ec510301361415585760f66109ec5103610a0c525b61010060016064818352015b36610a0c511015156100b557610291565b7f0100000000000000000000000000000000000000000000000000000000000000610a0c5135046109ec526109cc5160206109ac51026040015260016109ac51016109ac5260806109ec51101561013b5760016109cc5161044001526001610a0c516109cc5161046001376001610a0c5101610a0c5260216109cc51016109cc52610281565b60b86109ec5110156101d15760806109ec51036109cc51610440015260806109ec51036001610a0c51016109cc51610460013760816109ec5114156101ac5760807f01000000000000000000000000000000000000000000000000000000000000006001610a0c5101350410151558575b607f6109ec5103610a0c5101610a0c5260606109ec51036109cc51016109cc52610280565b60c06109ec51101561027d576001610a0c51013560b76109ec510360200352600051610a2c526038610a2c5110157f01000000000000000000000000000000000000000000000000000000000000006001610a0c5101350402155857610a2c516109cc516104400152610a2c5160b66109ec5103610a0c51016109cc516104600137610a2c5160b66109ec5103610a0c510101610a0c526020610a2c51016109cc51016109cc5261027f565bfe5b5b5b81516001018083528114156100a4575b5050601f6109ac511115155857602060206109ac5102016109005260206109005103610a0c5261010060016064818352015b6000610a0c5112156102d45761030a565b61090051610a0c516040015101610a0c51610900516104400301526020610a0c5103610a0c5281516001018083528114156102c3575b50506109cc516109005101610420526109cc5161090051016109005161044003f35b61000461033003610004600039610004610330036000f31b2d4f")
assert utils.bytes_to_int(_rlp_decoder_address) == utils.RLP_DECODER_ADDRESS

chain.head_state.gas_limit = 10**9

def check_gas(code, func=None, num_txs=1):
    if func:
        gas_estimate = tester.languages['viper'].gas_estimate(code)[func]
    else:
        gas_estimate = sum(tester.languages['viper'].gas_estimate(code).values())
    gas_actual = chain.head_state.receipts[-1].gas_used \
               - chain.head_state.receipts[-1-num_txs].gas_used \
               - chain.last_tx.intrinsic_gas_used*num_txs

    # Computed upper bound on the gas consumption should 
    # be greater than or equal to the amount of gas used
    if gas_estimate < gas_actual:
        raise Exception("Gas upper bound fail: bound %d actual %d" % (gas_estimate, gas_actual))

    print('Function name: {} - Gas estimate {}, Actual: {}'.format(
        func, gas_estimate, gas_actual)
    )


def gas_estimation_decorator(fn, source_code, func):
    def decorator(*args, **kwargs):
        @wraps(fn)
        def decorated_function(*args, **kwargs):
            result = fn(*args, **kwargs)
            check_gas(source_code, func)
            return result
        return decorated_function(*args, **kwargs)
    return decorator


def set_decorator_to_contract_function(contract, source_code, func):
    func_definition = getattr(contract, func)
    func_with_decorator = gas_estimation_decorator(
        func_definition, source_code, func
    )
    setattr(contract, func, func_with_decorator)


def get_contract_with_gas_estimation(
        source_code,
        *args, **kwargs):
    contract = chain.contract(source_code, language="viper", *args, **kwargs)

    for func_name in contract.translator.function_data:
        set_decorator_to_contract_function(
            contract, source_code, func_name
        )

    return contract


def get_contract(source_code, *args, **kwargs):
    return chain.contract(source_code, language="viper", *args, **kwargs)

G1 = [1, 2]

G1_times_two = [
    1368015179489954701390400359078579693043519447331113978918064868415326638035,
    9918110051302171585080402603319702774565515993150576347155970296011118125764
]

G1_times_three = [
    3353031288059533942658390886683067124040920775575537747144343083137631628272,
    19321533766552368860946552437480515441416830039777911637913418824951667761761
]

negative_G1 = [
    1,
    21888242871839275222246405745257275088696311157297823662689037894645226208581
]

curve_order = 21888242871839275222246405745257275088548364400416034343698204186575808495617

def get_logs(receipt, contract, event_name=None):
    contract_log_ids = contract.translator.event_data.keys() # All the log ids contract has
    # All logs originating from contract, and matching event_name (if specified)
    logs = [log for log in receipt.logs \
        if log.topics[0] in contract_log_ids and \
            log.address == contract.address and \
            (not event_name or \
                    contract.translator.event_data[log.topics[0]]['name'] == event_name)]
    assert len(logs) > 0, "No logs in last receipt"

    # Return all events decoded in the receipt
    return [contract.translator.decode_event(log.topics, log.data) for log in logs]

@pytest.fixture
def get_last_log():
    def get_last_log(tester, contract, event_name=None):
        receipt = tester.s.head_state.receipts[-1] # Only the receipts for the last block
        # Get last log event with correct name and return the decoded event
        return get_logs(receipt, contract, event_name=event_name)[-1]
    return get_last_log

@pytest.fixture
def assert_tx_failed():
    def assert_tx_failed(function_to_test, exception = tester.TransactionFailed):
        initial_state = tester.s.snapshot()
        with pytest.raises(exception):
            function_to_test()
        tester.s.revert(initial_state)
    return assert_tx_failed

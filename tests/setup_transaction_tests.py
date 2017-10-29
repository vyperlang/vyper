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

_rlp_decoder_address = inject_tx( "0xf90357808506fc23ac0083045d488080b9034461032c566000611438526000611458527f0100000000000000000000000000000000000000000000000000000000000000600035046114785260006114985260006114b85260c061147851101515585760f861147851101561006e5760bf61147851033614155857600161149852610098565b60013560f761147851036020035260005160f6611478510301361415585760f66114785103611498525b610fa060016103e8818352015b36611498511015156100b65761028c565b7f0100000000000000000000000000000000000000000000000000000000000000611498513504611478526114585160206114385102604001526001611438510161143852608061147851101561013c5760016114585161044001526001611498516114585161046001376001611498510161149852602161145851016114585261027c565b60b86114785110156101d25760806114785103611458516104400152608061147851036001611498510161145851610460013760816114785114156101ad5760807f010000000000000000000000000000000000000000000000000000000000000060016114985101350410151558575b607f61147851036114985101611498526060611478510361145851016114585261027b565b60c061147851101561027a57600161149851013560b76114785103602003526000516114b85260386114b85110157f0100000000000000000000000000000000000000000000000000000000000000600161149851013504021558576114b8516114585161044001526114b85160b6611478510361149851016114585161046001376114b85160b661147851036114985101016114985260206114b851016114585101611458525b5b5b81516001018083528114156100a5575b5050601f611438511115155857602060206114385102016114b85260206114b8510361149852610bb860016103e8818352015b60006114985112156102d057610306565b6114b851611498516040015101611498516114b851610440030152602061149851036114985281516001018083528114156102bf575b5050611458516114b8510161042052611458516114b851016114b85161044003f35b61000461032c0361000460003961000461032c036000f31b2d4f")
# assert utils.bytes_to_int(_rlp_decoder_address) == utils.RLP_DECODER_ADDRESS

chain.head_state.gas_limit = 10**9

def check_gas(code, function=None, num_txs=1):
    if function:
        gas_estimate = tester.languages['viper'].gas_estimate(code)[function]
    else:
        gas_estimate = sum(tester.languages['viper'].gas_estimate(code).values())
    gas_actual = chain.head_state.receipts[-1].gas_used \
               - chain.head_state.receipts[-1-num_txs].gas_used \
               - chain.last_tx.intrinsic_gas_used*num_txs

    #Computed upper bound on the gas consumption should 
    #be greater than or equal to the amount of gas used
    if gas_estimate < gas_actual:
        raise Exception("Gas upper bound fail: bound %d actual %d" % (gas_estimate, gas_actual))

    print('Function name: {} - Gas estimate {}, Actual: {}'.format(
        function, gas_estimate, gas_actual)
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

@pytest.fixture
def get_log():
    def get_log(tester, contract, event_name):
        event_ids_w_name = [k for k, v in \
                contract.translator.event_data.items() if v["name"] == event_name]
        assert len(event_ids_w_name) == 1, \
                "Contract doesn't have event {}!".format(event_name)
        event_id = event_ids_w_name[0]

        # Get the last logged event
        logs = tester.s.head_state.receipts[-1].logs[-1]

        # Ensure it has the event we are looking to decode
        assert logs.address == contract.address, \
                "This contract didn't originate the last event!"
        assert logs.topics[0] == event_id, \
                "The last event wasn't {}!".format(event_name)

        # Return the decoded event data
        return contract.translator.decode_event(logs.topics, logs.data)
    return get_log

@pytest.fixture
def assert_tx_failed():
    def assert_tx_failed(tester, function_to_test, exception = tester.TransactionFailed):
        initial_state = tester.s.snapshot()
        with pytest.raises(exception):
            function_to_test()
        tester.s.revert(initial_state)
    return assert_tx_failed

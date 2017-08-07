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

_rlp_decoder_address = inject_tx( "0xf90237808506fc23ac00830330888080b902246102128061000e60003961022056600060007f010000000000000000000000000000000000000000000000000000000000000060003504600060c082121515585760f882121561004d5760bf820336141558576001905061006e565b600181013560f783036020035260005160f6830301361415585760f6820390505b5b368112156101c2577f010000000000000000000000000000000000000000000000000000000000000081350483602086026040015260018501945060808112156100d55760018461044001526001828561046001376001820191506021840193506101bc565b60b881121561014357608081038461044001526080810360018301856104600137608181141561012e5760807f010000000000000000000000000000000000000000000000000000000000000060018401350412151558575b607f81038201915060608103840193506101bb565b60c08112156101b857600182013560b782036020035260005160388112157f010000000000000000000000000000000000000000000000000000000000000060018501350402155857808561044001528060b6838501038661046001378060b6830301830192506020810185019450506101ba565bfe5b5b5b5061006f565b601f841315155857602060208502016020810391505b6000821215156101fc578082604001510182826104400301526020820391506101d8565b808401610420528381018161044003f350505050505b6000f31b2d4f")
assert utils.bytes_to_int(_rlp_decoder_address) == utils.RLP_DECODER_ADDRESS

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
    assert gas_estimate >= gas_actual

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


def contract_with_gas_estimation(source_code, func_target_check_gas=None):
    contract = chain.contract(source_code, language="viper")

    if hasattr(contract, func_target_check_gas):
        func_definition = getattr(contract, func_target_check_gas)
        func_with_decorator = gas_estimation_decorator(
            func_definition, source_code, func_target_check_gas
        )
        setattr(contract, func_target_check_gas, func_with_decorator)

    return contract

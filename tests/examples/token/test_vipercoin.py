import pytest
from ethereum.tools import tester
import ethereum.utils as utils



def token_tester():
    t = tester
    tester.s = t.Chain()
    from viper import compiler
    t.languages['viper'] = compiler.Compiler()
    contract_code = open('examples/token/vipercoin.v.py').read()
    tester.c = tester.s.contract(contract_code, language='viper', args=[tester.accounts[0], FIVE_DAYS])
    return tester

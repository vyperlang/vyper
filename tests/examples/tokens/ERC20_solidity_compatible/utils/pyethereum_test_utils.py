""" Utility class for testing via pyethereum """

from ethereum.tools import tester
from ethereum import utils

import os
import unittest


# Extract language from contract extension
def extract_language(sourcefile):
    languages = {
        '.sol': 'solidity',
        '.vy': 'viper',
        '.py': 'viper'  # hack to handle new .v.py suggested Viper extension
    }
    _, ext = os.path.splitext(sourcefile)
    language = languages[ext]
    return language


def bytes_to_int(bytez):
    return int(utils.encode_hex(bytez), 16)


def int_to_bytes(i):
    return int(i).to_bytes(32, byteorder='big')


class PyEthereumTestCase(unittest.TestCase):

    t = None                # ethereum.tools.tester module
    s = None                # Chain object
    c = None                # Main contract
    initial_state = None    # Initial state of the chain

    @classmethod
    def setUpClass(cls):
        super(PyEthereumTestCase, cls).setUpClass()

        # Initialize tester, contract and expose relevant objects
        cls.t = tester
        cls.s = cls.t.Chain()

        cls.s.head_state.gas_limit = 10**80
        cls.s.head_state.set_balance(cls.t.a0, 10**80)
        cls.s.head_state.set_balance(cls.t.a1, 10**80)
        cls.s.head_state.set_balance(cls.t.a2, 10**80)
        cls.s.head_state.set_balance(cls.t.a3, 10**80)
        cls.initial_state = None

    def setUp(self):
        self.longMessage = True
        self.s.revert(self.initial_state)
        self.gas_used_before = self.s.head_state.gas_used
        self.refunds_before = self.s.head_state.refunds

        from ethereum.slogging import get_logger
        get_logger('eth.pb.tx')
        get_logger('eth.pb.msg')

    def tearDown(self):
        gas_used_after = self.s.head_state.gas_used
        print("Test used {} gas".format(gas_used_after - self.gas_used_before))

    def deploy_contract_from_file(self, contract_file, sender=None, value=0):
        with open(contract_file, 'r') as in_file:
                code = in_file.read()

        if sender is not None:
            return self.s.contract(code, language=extract_language(contract_file),
                                   sender=sender, value=value, startgas=10**20)
        else:
            return self.s.contract(code, language=extract_language(contract_file),
                                   value=value, startgas=10**20)

    def check_logs(self, topics, data):
        found = False
        for log_entry in self.s.head_state.receipts[-1].logs:
            if topics == log_entry.topics and data == log_entry.data:
                found = True

        self.assertTrue(found, self.s.head_state.receipts[-1].logs)

    def assert_tx_failed(self, function_to_test,
                     exception=tester.TransactionFailed):
        """ Ensure that transaction fails, reverting state
        (to prevent gas exhaustion) """
        initial_state = self.s.snapshot()
        self.assertRaises(exception, function_to_test)
        self.s.revert(initial_state)

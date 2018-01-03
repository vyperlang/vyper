# Author: Florian Tramer

import glob
import unittest
from ethereum import utils
from os.path import basename

from utils.pyethereum_test_utils import PyEthereumTestCase, bytes_to_int, int_to_bytes

# Base path to contracts from current directory
PATH_TO_CONTRACTS = ""

log_sigs = {
    'Transfer': bytes_to_int(utils.sha3("Transfer(address,address,uint256)")),
    'Approval': bytes_to_int(utils.sha3("Approval(address,address,uint256)"))
}


class TestERC20Flo(PyEthereumTestCase):

    def test_all(self):
        self.assertEqual(self.c.totalSupply(), 0, "Token not initially empty")

        orig_balance0 = self.s.head_state.get_balance(self.t.a0)
        orig_balance1 = self.s.head_state.get_balance(self.t.a1)

        self.c.deposit(sender=self.t.k0, value=1000)

        self.check_logs([log_sigs['Transfer'], 0, bytes_to_int(self.t.a0)],
                        int_to_bytes(1000))

        new_balance0 = self.s.head_state.get_balance(self.t.a0)

        self.assertEqual(self.c.totalSupply(), 1000, "Deposit not working")
        self.assertEqual(self.c.balanceOf(self.t.a0), 1000,
                         "Deposit not working")
        self.assertEqual(new_balance0, orig_balance0 - 1000,
                         "Deposit did not use funds")

        self.assertEqual(self.c.balanceOf(self.t.a1), 0,
                         "Account balance not empty initially")

        # If this fails, transfer worked although funds were insufficient
        self.assert_tx_failed(lambda: self.c.transfer(self.t.a1, 2000, sender=self.t.k0))

        self.assertTrue(self.c.transfer(self.t.a1, 500, sender=self.t.k0),
                        "Transfer not working")

        self.check_logs([log_sigs['Transfer'], bytes_to_int(self.t.a0),
                         bytes_to_int(self.t.a1)], int_to_bytes(500))

        self.assertEqual(self.c.totalSupply(), 1000, "Transfer changed balance")
        self.assertEqual(self.c.balanceOf(self.t.a0), 500,
                         "Transfer did not remove funds")
        self.assertEqual(self.c.balanceOf(self.t.a1), 500,
                         "Transfer did not add funds")

        self.assertTrue(self.c.approve(self.t.a0, 200, sender=self.t.k1),
                        "Approval did not work")

        self.check_logs([log_sigs['Approval'], bytes_to_int(self.t.a1),
                         bytes_to_int(self.t.a0)], int_to_bytes(200))

        # If this fails, Transfered larger value than approved
        self.assert_tx_failed(lambda: self.c.transferFrom(
            self.t.a1, self.t.a0, 201, sender=self.t.k0))

        self.assertTrue(self.c.transferFrom(
            self.t.a1, self.t.a0, 100, sender=self.t.k0),
            "Transfer not approved")

        self.check_logs([log_sigs['Transfer'], bytes_to_int(self.t.a1),
                         bytes_to_int(self.t.a0)], int_to_bytes(100))

        self.assertEqual(self.c.totalSupply(), 1000,
                          "TransferFrom changed balance")
        self.assertEqual(self.c.balanceOf(self.t.a0), 600,
                          "TransferFrom did not add funds")
        self.assertEqual(self.c.balanceOf(self.t.a1), 400,
                          "TransferFrom did not remove funds")

        # Check TransferFrom did not reduce allowance
        self.assert_tx_failed(lambda: self.c.transferFrom(
            self.t.a1, self.t.a0, 101, sender=self.t.k0))

        # If failed, withdraw more than balance allowed
        self.assert_tx_failed(lambda: self.c.withdraw(601, sender=self.t.k0))
        self.assertTrue(self.c.withdraw(500, sender=self.t.k0),
                        "Withdraw did not work")

        self.check_logs([log_sigs['Transfer'], bytes_to_int(self.t.a0), 0],
                        int_to_bytes(500))

        self.assertEqual(self.c.balanceOf(self.t.a0), 100,
                         "Withdraw did not reduce funds")
        new_balance0 = self.s.head_state.get_balance(self.t.a0)
        self.assertEqual(new_balance0, orig_balance0 - 500,
                         "Withdraw did not send funds")
        self.assertEqual(self.c.totalSupply(), 500,
                         "Withdraw did not change balance correctly")

        self.assertTrue(self.c.withdraw(100, sender=self.t.k0),
                        "Withdraw did not work")
        self.assertTrue(self.c.withdraw(400, sender=self.t.k1),
                        "Withdraw did not work")
        self.assertEqual(self.c.totalSupply(), 0,
                         "Token not empty after withdraw")

        new_balance0 = self.s.head_state.get_balance(self.t.a0)
        new_balance1 = self.s.head_state.get_balance(self.t.a1)

        self.assertEqual(new_balance0, orig_balance0 - 400,
                         "Withdraw did not send funds")
        self.assertEqual(new_balance1, orig_balance1 + 400,
                         "Withdraw did not send funds")

    @classmethod
    def listenForEvents(cls):
        cls.events = []
        cls.s.head_state.log_listeners.append(
            lambda x: cls.events.append(cls.c.translator.listen(x)))


class TestSingleERC20(TestERC20Flo):

    in_file = None

    @classmethod
    def setUpClass(cls):
        super(TestSingleERC20, cls).setUpClass()
        print("Testing {}".format(cls.in_file))
        gas_used_before = cls.s.head_state.gas_used
        cls.c = cls.deploy_contract_from_file(cls, cls.in_file)
        gas_used_after = cls.s.head_state.gas_used

        print("Deploying contract at {} used {} gas".format(
            utils.encode_hex(cls.c.address),
            gas_used_after - gas_used_before))

        cls.listenForEvents()
        cls.initial_state = cls.s.snapshot()

    def setUp(self):
        super().setUp()


test_suites = []
for f in glob.glob(PATH_TO_CONTRACTS + "nonviper/*") + glob.glob(PATH_TO_CONTRACTS + "/../../../../examples/tokens/ERC20_solidity_compatible/ERC20.v.py"):
    # ugly hack: copy the class instance to set a different file path
    # replace extension with underscore so that unittest parses it correctly
    cls_name = basename(f.replace('.', '_'))
    suite = type(cls_name, (TestSingleERC20,), {})
    globals()[cls_name] = suite
    suite.in_file = f
    test_suites.append(suite)


def load_tests(loader, tests, pattern):
    full_suite = unittest.TestSuite()
    for suite in test_suites:
        tests = loader.loadTestsFromTestCase(suite)
        full_suite.addTests(tests)
    return full_suite


if __name__ == '__main__':
    unittest.main(verbosity=2)

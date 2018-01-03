# Requires Python 3.6, Viper, and pyethereum dependencies
# Manually verified for full branch/decision, statement coverage (on Viper contract)
# Author: Philip Daian (contributions from Florian Tramer, Lorenz Breidenbach)

import unittest
from ethereum.tools import tester
import ethereum.utils as utils
import ethereum.abi as abi

from utils.pyethereum_test_utils import PyEthereumTestCase, bytes_to_int

MAX_UINT256 = (2 ** 256) - 1  # Max num256 value
MAX_UINT128 = (2 ** 128) - 1  # Max num128 value

# Base path to contracts from current directory
PATH_TO_CONTRACTS = "."


class TestERC20(PyEthereumTestCase):

    t = None
    s = None
    c = None

    # Topics for logged events
    transfer_topic = 0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef
    approval_topic = 0x8c5be1e5ebec7d5bd14f71427d1e84f3dd0314c0f7b2291e5b200ac8c7c3b925

    strict_log_mode = False

    @classmethod
    def setUpClass(cls):
        super(TestERC20, cls).setUpClass()

        # Initialize tester, contract and expose relevant objects
        cls.t = tester
        cls.s = cls.t.Chain()

        cls.s.head_state.gas_limit = 10**80
        cls.s.head_state.set_balance(cls.t.a0, 10**80)
        cls.s.head_state.set_balance(cls.t.a1, MAX_UINT256 * 3)
        cls.s.head_state.set_balance(cls.t.a2, utils.denoms.ether * 1)
        cls.initial_state = None

    @classmethod
    def listenForEvents(cls):
        cls.events = []
        cls.s.head_state.log_listeners.append(
            lambda x: cls.events.append(cls.c.translator.listen(x)))

    def setUp(self):
        self.s.revert(self.initial_state)
        super().setUp()

    def test_initial_state(self):
        # Check total supply is 0
        self.assertEqual(self.c.totalSupply(), 0)
        # Check several account balances as 0
        self.assertEqual(self.c.balanceOf(self.t.a1), 0)
        self.assertEqual(self.c.balanceOf(self.t.a2), 0)
        self.assertEqual(self.c.balanceOf(self.t.a3), 0)
        # Check several allowances as 0
        self.assertEqual(self.c.allowance(self.t.a1, self.t.a1), 0)
        self.assertEqual(self.c.allowance(self.t.a1, self.t.a2), 0)
        self.assertEqual(self.c.allowance(self.t.a1, self.t.a3), 0)
        self.assertEqual(self.c.allowance(self.t.a2, self.t.a3), 0)

    def test_deposit_and_withdraw(self):
        initial_a1_balance = self.s.head_state.get_balance(self.t.a1)
        initial_a2_balance = self.s.head_state.get_balance(self.t.a2)
        # Test scenario where a1 deposits 2, withdraws twice (check balance consistency)
        self.assertEqual(self.c.balanceOf(self.t.a1), 0)
        self.assertIsNone(self.c.deposit(value=2, sender=self.t.k1))
        self.assertEqual(self.c.balanceOf(self.t.a1), 2)
        # Check that 2 Wei have been debited from a1
        self.assertEqual(initial_a1_balance - self.s.head_state.get_balance(self.t.a1), 2)
        # ... and added to the contract
        self.assertEqual(self.s.head_state.get_balance(self.c.address), 2)
        self.assertTrue(self.c.withdraw(2, sender=self.t.k1))
        self.assertEqual(self.c.balanceOf(self.t.a1), 0)
        # a1 should have all his money back
        self.assertEqual(self.s.head_state.get_balance(self.t.a1), initial_a1_balance)
        self.assert_tx_failed(lambda: self.c.withdraw(2, sender=self.t.k1))
        self.assertEqual(self.c.balanceOf(self.t.a1), 0)
        # Test scenario where a2 deposits 0, withdraws (check balance consistency, false withdraw)
        self.assertIsNone(self.c.deposit(value=0, sender=self.t.k2))
        self.assertEqual(self.c.balanceOf(self.t.a2), 0)
        self.assertEqual(self.s.head_state.get_balance(self.t.a2), initial_a2_balance)
        self.assert_tx_failed(lambda: self.c.withdraw(2, sender=self.t.k2))
        # Check that a1 cannot withdraw after depleting their balance
        self.assert_tx_failed(lambda: self.c.withdraw(1, sender=self.t.k1))

    def test_totalSupply(self):
        # Test total supply initially, after deposit, between two withdraws, and after failed withdraw
        self.assertEqual(self.c.totalSupply(), 0)
        self.assertIsNone(self.c.deposit(value=2, sender=self.t.k1))
        self.assertEqual(self.c.totalSupply(), 2)
        self.assertTrue(self.c.withdraw(1, sender=self.t.k1))
        self.assertEqual(self.c.totalSupply(), 1)
        # Ensure total supply is equal to balance
        self.assertEqual(self.c.totalSupply(), self.s.head_state.get_balance(self.c.address))
        self.assertTrue(self.c.withdraw(1, sender=self.t.k1))
        self.assertEqual(self.c.totalSupply(), 0)
        self.assert_tx_failed(lambda: self.c.withdraw(1, sender=self.t.k1))
        self.assertEqual(self.c.totalSupply(), 0)
        # Test that 0-valued deposit can't affect supply
        self.assertIsNone(self.c.deposit(value=0, sender=self.t.k1))
        self.assertEqual(self.c.totalSupply(), 0)

    def test_transfer(self):
        # Test interaction between deposit/withdraw and transfer
        self.assert_tx_failed(lambda: self.c.withdraw(1, sender=self.t.k2))
        self.assertIsNone(self.c.deposit(value=2, sender=self.t.k1))
        self.assertTrue(self.c.withdraw(1, sender=self.t.k1))
        self.assertTrue(self.c.transfer(self.t.a2, 1, sender=self.t.k1))
        self.assert_tx_failed(lambda: self.c.withdraw(1, sender=self.t.k1))
        self.assertTrue(self.c.withdraw(1, sender=self.t.k2))
        self.assert_tx_failed(lambda: self.c.withdraw(1, sender=self.t.k2))
        # Ensure transfer fails with insufficient balance
        self.assert_tx_failed(lambda: self.c.transfer(self.t.a1, 1, sender=self.t.k2))
        # Ensure 0-transfer always succeeds
        self.assertTrue(self.c.transfer(self.t.a1, 0, sender=self.t.k2))

    def test_transferFromAndAllowance(self):
        # Test interaction between deposit/withdraw and transferFrom
        self.assert_tx_failed(lambda: self.c.withdraw(1, sender=self.t.k2))
        self.assertIsNone(self.c.deposit(value=1, sender=self.t.k1))
        self.assertIsNone(self.c.deposit(value=1, sender=self.t.k2))
        self.assertTrue(self.c.withdraw(1, sender=self.t.k1))
        # This should fail; no allowance or balance (0 always succeeds)
        self.assert_tx_failed(lambda: self.c.transferFrom(self.t.a1, self.t.a3, 1, sender=self.t.k2))
        self.assertTrue(self.c.transferFrom(self.t.a1, self.t.a3, 0, sender=self.t.k2))
        # Correct call to approval should update allowance (but not for reverse pair)
        self.assertTrue(self.c.approve(self.t.a2, 1, sender=self.t.k1))
        self.assertEqual(self.c.allowance(self.t.a1, self.t.a2, sender=self.t.k3), 1)
        self.assertEqual(self.c.allowance(self.t.a2, self.t.a1, sender=self.t.k2), 0)
        # transferFrom should succeed when allowed, fail with wrong sender
        self.assert_tx_failed(lambda: self.c.transferFrom(self.t.a2, self.t.a3, 1, sender=self.t.k3))
        self.assertEqual(self.c.balanceOf(self.t.a2), 1)
        self.assertTrue(self.c.approve(self.t.a1, 1, sender=self.t.k2))
        self.assertTrue(self.c.transferFrom(self.t.a2, self.t.a3, 1, sender=self.t.k1))
        # Allowance should be correctly updated after transferFrom
        self.assertEqual(self.c.allowance(self.t.a2, self.t.a1, sender=self.t.k2), 0)
        # transferFrom with no funds should fail despite approval
        self.assertTrue(self.c.approve(self.t.a1, 1, sender=self.t.k2))
        self.assertEqual(self.c.allowance(self.t.a2, self.t.a1, sender=self.t.k2), 1)
        self.assert_tx_failed(lambda: self.c.transferFrom(self.t.a2, self.t.a3, 1, sender=self.t.k1))
        # 0-approve should not change balance or allow transferFrom to change balance
        self.assertIsNone(self.c.deposit(value=1, sender=self.t.k2))
        self.assertEqual(self.c.allowance(self.t.a2, self.t.a1, sender=self.t.k2), 1)
        self.assertTrue(self.c.approve(self.t.a1, 0, sender=self.t.k2))
        self.assertEqual(self.c.allowance(self.t.a2, self.t.a1, sender=self.t.k2), 0)
        self.assertTrue(self.c.approve(self.t.a1, 0, sender=self.t.k2))
        self.assertEqual(self.c.allowance(self.t.a2, self.t.a1, sender=self.t.k2), 0)
        self.assert_tx_failed(lambda: self.c.transferFrom(self.t.a2, self.t.a3, 1, sender=self.t.k1))
        # Test that if non-zero approval exists, 0-approval is NOT required to proceed
        # a non-conformant implementation is described in countermeasures at
        # https://docs.google.com/document/d/1YLPtQxZu1UAvO9cZ1O2RPXBbT0mooh4DYKjA_jp-RLM/edit#heading=h.m9fhqynw2xvt
        # the final spec insists on NOT using this behavior
        self.assertEqual(self.c.allowance(self.t.a2, self.t.a1, sender=self.t.k2), 0)
        self.assertTrue(self.c.approve(self.t.a1, 1, sender=self.t.k2))
        self.assertEqual(self.c.allowance(self.t.a2, self.t.a1, sender=self.t.k2), 1)
        self.assertTrue(self.c.approve(self.t.a1, 2, sender=self.t.k2))
        self.assertEqual(self.c.allowance(self.t.a2, self.t.a1, sender=self.t.k2), 2)
        # Check that approving 0 then amount also works
        self.assertTrue(self.c.approve(self.t.a1, 0, sender=self.t.k2))
        self.assertEqual(self.c.allowance(self.t.a2, self.t.a1, sender=self.t.k2), 0)
        self.assertTrue(self.c.approve(self.t.a1, 5, sender=self.t.k2))
        self.assertEqual(self.c.allowance(self.t.a2, self.t.a1, sender=self.t.k2), 5)

    def test_maxInts(self):
        initial_a1_balance = self.s.head_state.get_balance(self.t.a1)
        # Check boundary conditions - a1 can deposit max amount
        self.assertIsNone(self.c.deposit(value=MAX_UINT256, sender=self.t.k1))
        self.assertEqual(initial_a1_balance - self.s.head_state.get_balance(self.t.a1), MAX_UINT256)
        self.assertEqual(self.c.balanceOf(self.t.a1), MAX_UINT256)
        self.assert_tx_failed(lambda: self.c.deposit(value=1, sender=self.t.k1))
        self.assert_tx_failed(lambda: self.c.deposit(value=MAX_UINT256, sender=self.t.k1))
        # Check that totalSupply cannot overflow, even when deposit from other sender
        self.assert_tx_failed(lambda: self.c.deposit(value=1, sender=self.t.k2))
        # Check that corresponding deposit is allowed after withdraw
        self.assertTrue(self.c.withdraw(1, sender=self.t.k1))
        self.assertIsNone(self.c.deposit(value=1, sender=self.t.k2))
        self.assert_tx_failed(lambda: self.c.deposit(value=1, sender=self.t.k2))
        self.assertTrue(self.c.transfer(self.t.a1, 1, sender=self.t.k2))
        # Assert that after obtaining max number of tokens, a1 can transfer those but no more
        self.assertEqual(self.c.balanceOf(self.t.a1), MAX_UINT256)
        self.assertTrue(self.c.transfer(self.t.a2, MAX_UINT256, sender=self.t.k1))
        self.assertEqual(self.c.balanceOf(self.t.a2), MAX_UINT256)
        self.assertEqual(self.c.balanceOf(self.t.a1), 0)
        # [ next line should never work in EVM ]
        self.assert_tx_failed(lambda: self.c.transfer(self.t.a1, MAX_UINT256 + 1, sender=self.t.k2), exception=abi.ValueOutOfBounds)
        # Check approve/allowance w max possible token values
        self.assertEqual(self.c.balanceOf(self.t.a2), MAX_UINT256)
        self.assertTrue(self.c.approve(self.t.a1, MAX_UINT256, sender=self.t.k2))
        self.assertTrue(self.c.transferFrom(self.t.a2, self.t.a1, MAX_UINT256, sender=self.t.k1))
        self.assertEqual(self.c.balanceOf(self.t.a1), MAX_UINT256)
        self.assertEqual(self.c.balanceOf(self.t.a2), 0)
        # Check that max amount can be withdrawn
        # (-1 because a1 withdrew from a2 transferring in)
        self.assertEqual(initial_a1_balance - MAX_UINT256, self.s.head_state.get_balance(self.t.a1) - 1)
        self.assertTrue(self.c.withdraw(MAX_UINT256, sender=self.t.k1))
        self.assertEqual(self.c.balanceOf(self.t.a1), 0)
        self.assertEqual(initial_a1_balance, self.s.head_state.get_balance(self.t.a1) - 1)

    def test_payability(self):
        # Make sure functions are appopriately payable (or not)

        # Payable functions - ensure success
        self.assertIsNone(self.c.deposit(value=2, sender=self.t.k1))
        # Non payable functions - ensure all fail with value, succeed without
        self.assert_tx_failed(lambda: self.c.withdraw(0, value=2, sender=self.t.k1))
        self.assertTrue(self.c.withdraw(0, value=0, sender=self.t.k1))
        self.assert_tx_failed(lambda: self.c.totalSupply(value=2, sender=self.t.k1))
        self.assertEqual(self.c.totalSupply(value=0, sender=self.t.k1), 2)
        self.assert_tx_failed(lambda: self.c.balanceOf(self.t.a1, value=2, sender=self.t.k1))
        self.assertEqual(self.c.balanceOf(self.t.a1, value=0, sender=self.t.k1), 2)
        self.assert_tx_failed(lambda: self.c.transfer(self.t.a2, 0, value=2, sender=self.t.k1))
        self.assertTrue(self.c.transfer(self.t.a2, 0, value=0, sender=self.t.k1))
        self.assert_tx_failed(lambda: self.c.approve(self.t.a2, 1, value=2, sender=self.t.k1))
        self.assertTrue(self.c.approve(self.t.a2, 1, value=0, sender=self.t.k1))
        self.assert_tx_failed(lambda: self.c.allowance(self.t.a1, self.t.a2, value=2, sender=self.t.k1))
        self.assertEqual(self.c.allowance(self.t.a1, self.t.a2, value=0, sender=self.t.k1), 1)
        self.assert_tx_failed(lambda: self.c.transferFrom(self.t.a1, self.t.a2, 0, value=2, sender=self.t.k1))
        self.assertTrue(self.c.transferFrom(self.t.a1, self.t.a2, 0, value=0, sender=self.t.k1))

    def test_raw_logs(self):
        self.s.head_state.receipts[-1].logs = []
        # Check that deposit appropriately emits Deposit event
        self.assertIsNone(self.c.deposit(value=2, sender=self.t.k1))
        self.check_logs([self.transfer_topic, 0, bytes_to_int(self.t.a1)], (2).to_bytes(32, byteorder='big'))
        self.assertIsNone(self.c.deposit(value=0, sender=self.t.k1))
        self.check_logs([self.transfer_topic, 0, bytes_to_int(self.t.a1)], (0).to_bytes(32, byteorder='big'))

        # Check that withdraw appropriately emits Withdraw event
        self.assertTrue(self.c.withdraw(1, sender=self.t.k1))
        self.check_logs([self.transfer_topic, bytes_to_int(self.t.a1), 0], (1).to_bytes(32, byteorder='big'))
        self.assertTrue(self.c.withdraw(0, sender=self.t.k1))
        self.check_logs([self.transfer_topic, bytes_to_int(self.t.a1), 0], (0).to_bytes(32, byteorder='big'))

        # Check that transfer appropriately emits Transfer event
        self.assertTrue(self.c.transfer(self.t.a2, 1, sender=self.t.k1))
        self.check_logs([self.transfer_topic, bytes_to_int(self.t.a1), bytes_to_int(self.t.a2)], (1).to_bytes(32, byteorder='big'))
        self.assertTrue(self.c.transfer(self.t.a2, 0, sender=self.t.k1))
        self.check_logs([self.transfer_topic, bytes_to_int(self.t.a1), bytes_to_int(self.t.a2)], (0).to_bytes(32, byteorder='big'))

        # Check that approving amount emits events
        self.assertTrue(self.c.approve(self.t.a1, 1, sender=self.t.k2))
        self.check_logs([self.approval_topic, bytes_to_int(self.t.a2), bytes_to_int(self.t.a1)], (1).to_bytes(32, byteorder='big'))
        self.assertTrue(self.c.approve(self.t.a2, 0, sender=self.t.k3))
        self.check_logs([self.approval_topic, bytes_to_int(self.t.a3), bytes_to_int(self.t.a2)], (0).to_bytes(32, byteorder='big'))

        # Check that transferFrom appropriately emits Transfer event
        self.assertTrue(self.c.transferFrom(self.t.a2, self.t.a3, 1, sender=self.t.k1))
        self.check_logs([self.transfer_topic, bytes_to_int(self.t.a2), bytes_to_int(self.t.a3)], (1).to_bytes(32, byteorder='big'))
        self.assertTrue(self.c.transferFrom(self.t.a2, self.t.a3, 0, sender=self.t.k1))
        self.check_logs([self.transfer_topic, bytes_to_int(self.t.a2), bytes_to_int(self.t.a3)], (0).to_bytes(32, byteorder='big'))

        # Check that no other ERC-compliant calls emit any events
        self.s.head_state.receipts[-1].logs = []
        self.assertEqual(self.c.totalSupply(), 1)
        self.assertEqual(self.s.head_state.receipts[-1].logs, [])
        self.assertEqual(self.c.balanceOf(self.t.a1), 0)
        self.assertEqual(self.s.head_state.receipts[-1].logs, [])
        self.assertEqual(self.c.allowance(self.t.a1, self.t.a2), 0)
        self.assertEqual(self.s.head_state.receipts[-1].logs, [])

        # Check that failed (Deposit, Withdraw, Transfer) calls emit no events
        self.assert_tx_failed(lambda: self.c.deposit(value=MAX_UINT256, sender=self.t.k1))
        self.assertEqual(self.s.head_state.receipts[-1].logs, [])
        self.assert_tx_failed(lambda: self.c.withdraw(1, sender=self.t.k1))
        self.assertEqual(self.s.head_state.receipts[-1].logs, [])
        self.assert_tx_failed(lambda: self.c.transfer(self.t.a2, 1, sender=self.t.k1))
        self.assertEqual(self.s.head_state.receipts[-1].logs, [])
        self.assert_tx_failed(lambda: self.c.transferFrom(self.t.a2, self.t.a3, 1, sender=self.t.k1))
        self.assertEqual(self.s.head_state.receipts[-1].logs, [])

    def test_failed_send_in_withdraw(self):
        external_code = """
            contract ERC20 {
                function deposit() payable;
                function withdraw(uint256 _value) returns (bool success);
            }

            contract Dummy {

                address private erc20_addr;
                uint256 val;

                function Dummy(address _erc20_addr) {
                    erc20_addr = _erc20_addr;
                }

                function my_deposit() external payable {
                    val = msg.value;
                    ERC20(erc20_addr).deposit.value(val)();
                }

                function my_withdraw() returns (bool success) {
                    return ERC20(erc20_addr).withdraw(val);
                }

                function() external payable {
                    throw;
                }
            }
        """

        # deploy the contract and pass the ERC20 contract's address as argument
        ext = self.s.contract(external_code, args=[self.c.address], language='solidity')

        # deposit should work and a Deposit event should be logged
        self.assertIsNone(ext.my_deposit(value=2))
        self.check_logs([self.transfer_topic, 0, bytes_to_int(ext.address)], (2).to_bytes(32, byteorder='big'))

        # withdraw should throw
        self.assert_tx_failed(lambda: ext.my_withdraw())

        # re-deploy the contract with a working default function
        external_code2 = external_code.replace("throw", "return")
        ext2 = self.s.contract(external_code2, args=[self.c.address], language='solidity')

        # deposit should work and yield the correct event
        self.assertIsNone(ext2.my_deposit(value=2))
        self.check_logs([self.transfer_topic, 0, bytes_to_int(ext2.address)], (2).to_bytes(32, byteorder='big'))

        # withdraw should work and yield the correct event
        self.assertTrue(ext2.my_withdraw())
        self.check_logs([self.transfer_topic, bytes_to_int(ext2.address), 0], (2).to_bytes(32, byteorder='big'))


class TestViperERC20(TestERC20):

    @classmethod
    def setUpClass(cls):
        super(TestViperERC20, cls).setUpClass()

        from viper import compiler
        cls.t.languages['viper'] = compiler.Compiler()
        contract_code = open(PATH_TO_CONTRACTS + '/../../../../examples/tokens/ERC20_solidity_compatible/ERC20.v.py').read()
        cls.c = cls.s.contract(contract_code, language='viper')
        # Bad version of contract where totalSupply / num_issued never gets updated after init
        # (required for full decision/branch coverage)
        bad_code = contract_code.replace("self.num_issued = num256_add", "x = num256_add")
        cls.c_bad = cls.s.contract(bad_code, language='viper')

        cls.initial_state = cls.s.snapshot()
        cls.strict_log_mode = True
        cls.listenForEvents()

    def setUp(self):
        super().setUp()

    def test_bad_transfer(self):
        # Ensure transfer fails if it would otherwise overflow balance
        # (bad contract is used or overflow checks on total supply would fail)
        self.assertIsNone(self.c_bad.deposit(value=MAX_UINT256, sender=self.t.k1))
        self.assertIsNone(self.c_bad.deposit(value=1, sender=self.t.k2))
        self.assert_tx_failed(lambda: self.c_bad.transfer(self.t.a1, 1, sender=self.t.k2))
        self.assertTrue(self.c_bad.transfer(self.t.a2, MAX_UINT256 - 1, sender=self.t.k1))

    def test_bad_deposit(self):
        # Check that, in event when totalSupply is corrupted, it can't be underflowed
        self.assertEqual(self.c_bad.balanceOf(self.t.a1), 0)
        self.assertIsNone(self.c_bad.deposit(value=2, sender=self.t.k1))
        self.assertEqual(self.c_bad.balanceOf(self.t.a1), 2)
        self.assert_tx_failed(lambda: self.c_bad.withdraw(2, sender=self.t.k1))

    def test_bad_transferFrom(self):
        # Ensure transferFrom fails if it would otherwise overflow balance
        self.assertIsNone(self.c_bad.deposit(value=MAX_UINT256, sender=self.t.k1))
        self.assertIsNone(self.c_bad.deposit(value=1, sender=self.t.k2))
        self.assertTrue(self.c_bad.approve(self.t.a1, 1, sender=self.t.k2))
        self.assert_tx_failed(lambda: self.c_bad.transferFrom(self.t.a2, self.t.a1, 1, sender=self.t.k1))
        self.assertTrue(self.c_bad.approve(self.t.a2, MAX_UINT256, sender=self.t.k1))
        self.assertEqual(self.c_bad.allowance(self.t.a1, self.t.a2, sender=self.t.k3), MAX_UINT256)
        self.assertTrue(self.c_bad.transferFrom(self.t.a1, self.t.a2, MAX_UINT256 - 1, sender=self.t.k2))
        self.assertEqual(self.c_bad.allowance(self.t.a1, self.t.a2, sender=self.t.k3), 1)


class TestSolidity1ERC20(TestERC20):

    @classmethod
    def setUpClass(cls):
        super(TestSolidity1ERC20, cls).setUpClass()

        contract_code = open(PATH_TO_CONTRACTS + '/nonviper/ERC20_solidity_1.sol').read()
        cls.c = cls.s.contract(contract_code, language='solidity')

        cls.initial_state = cls.s.snapshot()
        cls.strict_log_mode = True
        cls.listenForEvents()

    def setUp(self):
        super().setUp()


class TestSolidity2ERC20(TestERC20):

    @classmethod
    def setUpClass(cls):
        super(TestSolidity2ERC20, cls).setUpClass()

        contract_code = open(PATH_TO_CONTRACTS + '/nonviper/ERC20_solidity_2.sol').read()
        cls.c = cls.s.contract(contract_code, language='solidity')

        cls.initial_state = cls.s.snapshot()
        cls.strict_log_mode = True
        cls.listenForEvents()

    def setUp(self):
        super().setUp()


def load_tests(loader, tests, pattern):
    full_suite = unittest.TestSuite()

    for suite in [TestViperERC20, TestSolidity1ERC20, TestSolidity2ERC20]:
        tests = loader.loadTestsFromTestCase(suite)
        full_suite.addTests(tests)
    return full_suite


if __name__ == '__main__':
    unittest.main(verbosity=2)

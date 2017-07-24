# Requires Python 3.6, Viper, and pyethereum dependencies

import unittest
from ethereum.tools import tester
import ethereum.utils as utils
import ethereum.abi as abi

MAX_UINT256 = 115792089237316195423570985008687907853269984665640564039457584007913129639935 # Max num256 value

def assert_tx_failed(erc20_tester, function_to_test, exception = tester.TransactionFailed):
    """ Ensure that transaction fails, reverting state (to prevent gas exhaustion) """
    initial_state = erc20_tester.s.snapshot()
    erc20_tester.assertRaises(exception, function_to_test)
    erc20_tester.s.revert(initial_state)

class TestERC20(unittest.TestCase):
    def setUp(self):
        # Initialize tester, contract and expose relevant objects
        self.t = tester
        self.s = self.t.Chain({self.t.a1: {"balance": MAX_UINT256 * 3}, self.t.a2: {"balance": utils.denoms.ether * 1}})
        from viper import compiler
        self.t.languages['viper'] = compiler.Compiler()
        self.c = self.s.contract(open('erc20.v.py').read(), language='viper')

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
        self.assertTrue(self.c.deposit(value=2, sender=self.t.k1))
        self.assertEqual(self.c.balanceOf(self.t.a1), 2)
        # Check that 2 Wei have been debited from a1
        self.assertEqual(initial_a1_balance - self.s.head_state.get_balance(self.t.a1), 2)
        # ... and added to the contract
        self.assertEqual(self.s.head_state.get_balance(self.c.address), 2)
        self.assertTrue(self.c.withdraw(2, sender=self.t.k1))
        self.assertEqual(self.c.balanceOf(self.t.a1), 0)
        # a1 should have all his money back
        self.assertEqual(self.s.head_state.get_balance(self.t.a1), initial_a1_balance)
        self.assertFalse(self.c.withdraw(2, sender=self.t.k1))
        self.assertEqual(self.c.balanceOf(self.t.a1), 0)
        # Test scenario where a2 deposits 0, withdraws (check balance consistency, false withdraw)
        self.assertTrue(self.c.deposit(value=0, sender=self.t.k2))
        self.assertEqual(self.c.balanceOf(self.t.a2), 0)
        self.assertEqual(self.s.head_state.get_balance(self.t.a2), initial_a2_balance)
        self.assertFalse(self.c.withdraw(2, sender=self.t.k2))
        # Check that a1 cannot withdraw after depleting their balance
        self.assertFalse(self.c.withdraw(1, sender=self.t.k1))

    def test_maxInts(self):
        initial_a1_balance = self.s.head_state.get_balance(self.t.a1)
        # Check boundary conditions - a1 can deposit max amount
        self.assertTrue(self.c.deposit(value=MAX_UINT256, sender=self.t.k1))
        self.assertEqual(initial_a1_balance - self.s.head_state.get_balance(self.t.a1), MAX_UINT256)
        self.assertEqual(self.c.balanceOf(self.t.a1), MAX_UINT256)
        self.assertFalse(self.c.deposit(value=1, sender=self.t.k1))
        self.assertFalse(self.c.deposit(value=MAX_UINT256, sender=self.t.k1))
        # Check that totalSupply cannot overflow, even when deposit from other sender
        self.assertFalse(self.c.deposit(value=1, sender=self.t.k2))
        # Check that corresponding deposit is allowed after withdraw
        self.assertTrue(self.c.withdraw(1, sender=self.t.k1))
        self.assertTrue(self.c.deposit(value=1, sender=self.t.k2))
        self.assertFalse(self.c.deposit(value=1, sender=self.t.k2))
        self.assertTrue(self.c.transfer(self.t.a1, 1, sender=self.t.k2))
        # Assert that after obtaining max number of tokens, a1 can transfer those but no more
        self.assertEqual(self.c.balanceOf(self.t.a1), MAX_UINT256)
        self.assertTrue(self.c.transfer(self.t.a2, MAX_UINT256, sender=self.t.k1))
        self.assertEqual(self.c.balanceOf(self.t.a2), MAX_UINT256)
        self.assertEqual(self.c.balanceOf(self.t.a1), 0)
        # [ next line should never work in EVM ]
        assert_tx_failed(self, lambda: self.c.transfer(self.t.a1, MAX_UINT256 + 1, sender=self.t.k2), exception=abi.ValueOutOfBounds)
        # Check approve/allowance w max possible token values
        self.assertEqual(self.c.balanceOf(self.t.a2), MAX_UINT256)
        self.assertTrue(self.c.approve(self.t.a1, MAX_UINT256, sender=self.t.k2))
        self.assertTrue(self.c.transferFrom(self.t.a2, self.t.a1, MAX_UINT256, sender=self.t.k2))
        self.assertEqual(self.c.balanceOf(self.t.a1), MAX_UINT256)


    def test_totalSupply(self):
        # Test total supply initially, after deposit, between two withdraws, and after failed withdraw
        self.assertEqual(self.c.totalSupply(), 0)
        self.assertTrue(self.c.deposit(value=2, sender=self.t.k1))
        self.assertEqual(self.c.totalSupply(), 2)
        self.assertTrue(self.c.withdraw(1, sender=self.t.k1))
        self.assertEqual(self.c.totalSupply(), 1)
        # Ensure total supply is equal to balance
        self.assertEqual(self.c.totalSupply(), self.s.head_state.get_balance(self.c.address))
        self.assertTrue(self.c.withdraw(1, sender=self.t.k1))
        self.assertEqual(self.c.totalSupply(), 0)
        self.assertFalse(self.c.withdraw(1, sender=self.t.k1))
        self.assertEqual(self.c.totalSupply(), 0)
        # Test that 0-valued deposit can't affect supply
        self.assertTrue(self.c.deposit(value=0, sender=self.t.k1))
        self.assertEqual(self.c.totalSupply(), 0)

    def test_transfer(self):
        # Test interaction between deposit/withdraw and transfer
        self.assertFalse(self.c.withdraw(1, sender=self.t.k2))
        self.assertTrue(self.c.deposit(value=2, sender=self.t.k1))
        self.assertTrue(self.c.withdraw(1, sender=self.t.k1))
        self.assertTrue(self.c.transfer(self.t.a2, 1, sender=self.t.k1))
        self.assertFalse(self.c.withdraw(1, sender=self.t.k1))
        self.assertTrue(self.c.withdraw(1, sender=self.t.k2))
        self.assertFalse(self.c.withdraw(1, sender=self.t.k2))

    def test_transferFromAndAllowance(self):
        # Test interaction between deposit/withdraw and transferFrom
        self.assertFalse(self.c.withdraw(1, sender=self.t.k2))
        self.assertTrue(self.c.deposit(value=1, sender=self.t.k1))
        self.assertTrue(self.c.deposit(value=1, sender=self.t.k2))
        self.assertTrue(self.c.withdraw(1, sender=self.t.k1))
        # This should fail; no allowance or balance
        self.assertFalse(self.c.transferFrom(self.t.a1, self.t.a2, 1, sender=self.t.k3))
        # Correct call to approval should update allowance (but not for reverse pair)
        self.assertTrue(self.c.approve(self.t.a2, 1, sender=self.t.k1))
        self.assertEqual(self.c.allowance(self.t.a1, self.t.a2, sender=self.t.k3), 1)
        self.assertEqual(self.c.allowance(self.t.a2, self.t.a1, sender=self.t.k2), 0)
        self.s.mine()
        # transferFrom should succeed when allowed, fail with wrong to parameter
        self.assertFalse(self.c.transferFrom(self.t.a2, self.t.a3, 1, sender=self.t.k2))
        self.assertEqual(self.c.balanceOf(self.t.a2), 1)
        self.assertTrue(self.c.approve(self.t.a1, 1, sender=self.t.k2))
        self.assertTrue(self.c.transferFrom(self.t.a2, self.t.a1, 1, sender=self.t.k3))
        # Allowance should be correctly updated after transferFrom
        self.assertEqual(self.c.allowance(self.t.a2, self.t.a1, sender=self.t.k2), 0)
        # transferFrom with no funds should fail despite approval
        self.assertTrue(self.c.approve(self.t.a1, 1, sender=self.t.k2))
        self.assertEqual(self.c.allowance(self.t.a2, self.t.a1, sender=self.t.k2), 1)
        self.assertFalse(self.c.transferFrom(self.t.a2, self.t.a1, 1, sender=self.t.k3))
        # 0-approve should not change balance or allow transferFrom to change balance
        self.assertTrue(self.c.deposit(value=1, sender=self.t.k2))
        self.assertEqual(self.c.allowance(self.t.a2, self.t.a1, sender=self.t.k2), 1)
        self.assertTrue(self.c.approve(self.t.a1, 0, sender=self.t.k2))
        self.assertEqual(self.c.allowance(self.t.a2, self.t.a1, sender=self.t.k2), 0)
        self.assertTrue(self.c.approve(self.t.a1, 0, sender=self.t.k2))
        self.assertEqual(self.c.allowance(self.t.a2, self.t.a1, sender=self.t.k2), 0)
        self.assertFalse(self.c.transferFrom(self.t.a2, self.t.a1, 1, sender=self.t.k3))
        # Test that if non-zero approval exists, 0-approval is required to proceed
        # as described in countermeasures at
        # https://docs.google.com/document/d/1YLPtQxZu1UAvO9cZ1O2RPXBbT0mooh4DYKjA_jp-RLM/edit#heading=h.m9fhqynw2xvt
        self.assertEqual(self.c.allowance(self.t.a2, self.t.a1, sender=self.t.k2), 0)
        self.assertTrue(self.c.approve(self.t.a1, 1, sender=self.t.k2))
        self.assertEqual(self.c.allowance(self.t.a2, self.t.a1, sender=self.t.k2), 1)
        self.assertFalse(self.c.approve(self.t.a1, 2, sender=self.t.k2))
        self.assertEqual(self.c.allowance(self.t.a2, self.t.a1, sender=self.t.k2), 1)
        # Check that approving 0 then amount works
        self.assertTrue(self.c.approve(self.t.a1, 0, sender=self.t.k2))
        self.assertEqual(self.c.allowance(self.t.a2, self.t.a1, sender=self.t.k2), 0)
        self.assertTrue(self.c.approve(self.t.a1, 5, sender=self.t.k2))
        self.assertEqual(self.c.allowance(self.t.a2, self.t.a1, sender=self.t.k2), 5)


    def test_payability(self):
        # Make sure functions are appopriately payable (or not)

        # General payable function checker tests
        self.assertIsNone(self.c.payable(True, 2, value=2, sender=self.t.k1))
        self.assertIsNone(self.c.payable(True, 0, sender=self.t.k1))
        self.assertIsNone(self.c.payable(False, 0, sender=self.t.k1))
        # This tx should fail (would have value 1, non-payable)
        assert_tx_failed(self, lambda : self.c.payable(False, 1, sender=self.t.k1))

        # Payable functions - ensure success
        self.assertTrue(self.c.deposit(value=2, sender=self.t.k1))

        # Non payable functions - ensure all fail
        assert_tx_failed(self, lambda :self.c.withdraw(0, value=2, sender=self.t.k1))
        assert_tx_failed(self, lambda :self.c.totalSupply(value=2, sender=self.t.k1))
        assert_tx_failed(self, lambda :self.c.balanceOf(self.t.a1, value=2, sender=self.t.k1))
        assert_tx_failed(self, lambda :self.c.transfer(self.t.a2, 0, value=2, sender=self.t.k1))
        assert_tx_failed(self, lambda :self.c.approve(self.t.a2, 1, value=2, sender=self.t.k1))
        assert_tx_failed(self, lambda :self.c.allowance(self.t.a1, self.t.a2, value=2, sender=self.t.k1))
        assert_tx_failed(self, lambda :self.c.transferFrom(self.t.a1, self.t.a2, 1, value=2, sender=self.t.k1))
        assert_tx_failed(self, lambda :self.c.is_overflow_add(0, 0, value=2, sender=self.t.k1))
        assert_tx_failed(self, lambda :self.c.is_overflow_sub(0, 0, value=2, sender=self.t.k1))


if __name__ == '__main__':
    unittest.main()

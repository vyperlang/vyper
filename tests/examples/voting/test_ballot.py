from ethereum.tools import tester
import ethereum.utils as utils
import ethereum.abi as abi

def assert_tx_failed(ballot_tester, function_to_test, exception = tester.TransactionFailed):
    """ Ensure that transaction fails, reverting state (to prevent gas exhaustion) """
    initial_state = ballot_tester.s.snapshot()
    ballot_tester.assertRaises(exception, function_to_test)
    ballot_tester.s.revert(initial_state)

class TestVoting(unittest.TestCase):
    def setUp(self):
        # Initialize tester, contract and expose relevant objects
        self.t = tester
        self.s = self.t.Chain()
        from viper import compiler
        self.t.languages['viper'] = compiler.Compiler()
        contract_code = open('examples/voting/ballot.v.py').read()
        self.c = self.s.contract(contract_code, language='viper', args=[["Clinton", "Trump"]])

    def test_initial_state(self):
        # Check chairperson is msg.sender
        self.assertEqual(utils.remove_0x_head(self.c.get_chairperson()), self.t.a0.hex())
        # Check propsal names are correct
        self.assertEqual(self.c.get_proposals__name(0), b'Clinton\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00')
        self.assertEqual(self.c.get_proposals__name(1), b'Trump\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00')
        # Check proposal vote_count is 0
        self.assertEqual(self.c.get_proposals__vote_count(0), 0)
        self.assertEqual(self.c.get_proposals__vote_count(1), 0)
        # Check voter_count is 0
        self.assertEqual(self.c.get_voter_count(), 0)
        # Check voter starts empty
        self.assertEqual(self.c.get_voters__delegate(), '0x0000000000000000000000000000000000000000')
        self.assertEqual(self.c.get_voters__vote(), 0)
        self.assertEqual(self.c.get_voters__voted(), False)
        self.assertEqual(self.c.get_voters__weight(), 0)

    def test_give_the_right_to_vote(self):
        self.c.give_right_to_vote(self.t.a1)
        # Check voter given right has weight of 1
        self.assertEqual(self.c.get_voters__weight(self.t.a1), 1)
        # Check no other voter attributes have changed
        self.assertEqual(self.c.get_voters__delegate(self.t.a1), '0x0000000000000000000000000000000000000000')
        self.assertEqual(self.c.get_voters__vote(self.t.a1), 0)
        self.assertEqual(self.c.get_voters__voted(self.t.a1), False)
        # Chairperson can give themselves the right to vote
        self.c.give_right_to_vote(self.t.a0)
        # Check chairperson has weight of 1
        self.assertEqual(self.c.get_voters__weight(self.t.a0), 1)
        # Check voter_acount is 2
        self.assertEqual(self.c.get_voter_count(), 2)
        # Check several giving rights to vote
        self.c.give_right_to_vote(self.t.a2)
        self.c.give_right_to_vote(self.t.a3)
        self.c.give_right_to_vote(self.t.a4)
        self.c.give_right_to_vote(self.t.a5)
        # Check voter_acount is now 6
        self.assertEqual(self.c.get_voter_count(), 6)
        # Check chairperson cannot give the right to vote twice to the same voter
        assert_tx_failed(self, lambda: self.c.give_right_to_vote(self.t.a5))
        # Check voters weight didn't change
        self.assertEqual(self.c.get_voters__weight(self.t.a5), 1)

    def test_delegate(self):
        self.c.give_right_to_vote(self.t.a0)
        self.c.give_right_to_vote(self.t.a1)
        self.c.give_right_to_vote(self.t.a2)
        self.c.give_right_to_vote(self.t.a3)
        # Voter can delegate
        self.c.delegate(self.t.a0, sender=self.t.k1)
        # Voters weight is 1
        self.assertEqual(self.c.get_voters__weight(self.t.a1), 1)
        # Voter has voted
        self.assertEqual(self.c.get_voters__voted(self.t.a1), True)
        # Delegates weight is 2
        self.assertEqual(self.c.get_voters__weight(self.t.a0), 2)
        # Voter cannot delegate twice
        assert_tx_failed(self, lambda: self.c.delegate(self.t.a2, sender=self.t.k1))
        # Voter cannot delegate to themselves
        assert_tx_failed(self, lambda: self.c.delegate(self.t.a2, sender=self.t.k2))
        # Voter can delegatation is passed up to final delegate
        self.c.delegate(self.t.a1, sender=self.t.k3)
        # Delegates weight is 3
        self.assertEqual(self.c.get_voters__weight(self.t.a0), 3)

    def test_vote(self):
        self.c.give_right_to_vote(self.t.a0)
        self.c.give_right_to_vote(self.t.a1)
        self.c.give_right_to_vote(self.t.a2)
        self.c.give_right_to_vote(self.t.a3)
        self.c.give_right_to_vote(self.t.a4)
        self.c.give_right_to_vote(self.t.a5)
        self.c.give_right_to_vote(self.t.a6)
        self.c.delegate(self.t.a0, sender=self.t.k1)
        self.c.delegate(self.t.a1, sender=self.t.k3)
        # Voter can vote
        self.c.vote(0)
        # Vote count changes based on voters weight
        self.assertEqual(self.c.get_proposals__vote_count(0), 3)
        # Voter cannot vote twice
        assert_tx_failed(self, lambda: self.c.vote(0))
        # Voter cannot vote if they've delegated
        assert_tx_failed(self, lambda: self.c.vote(0, sender=self.t.k1))
        # Several voters can voter
        self.c.vote(1, sender=self.t.k4)
        self.c.vote(1, sender=self.t.k2)
        self.c.vote(1, sender=self.t.k5)
        self.c.vote(1, sender=self.t.k6)
        self.assertEqual(self.c.get_proposals__vote_count(1), 4)

    def test_winning_proposal(self):
        self.c.give_right_to_vote(self.t.a0)
        self.c.give_right_to_vote(self.t.a1)
        self.c.give_right_to_vote(self.t.a2)
        self.c.vote(0)
        # Proposal 0 is now winning
        self.assertEqual(self.c.winning_proposal(), 0)
        self.c.vote(1, sender=self.t.k1)
        # Proposal 0 is still winning (the proposals are tied)
        self.assertEqual(self.c.winning_proposal(), 0)
        self.c.vote(1, sender=self.t.k2)
        # Proposal 2 is now winning
        self.assertEqual(self.c.winning_proposal(), 1)

    def test_winner_namer(self):
        self.c.give_right_to_vote(self.t.a0)
        self.c.give_right_to_vote(self.t.a1)
        self.c.give_right_to_vote(self.t.a2)
        self.c.delegate(self.t.a1, sender=self.t.k2)
        self.c.vote(0)
        # Proposal 0 is now winning
        self.assertEqual(self.c.winner_name(), b'Clinton\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00')
        self.c.vote(1, sender=self.t.k1)
        # Proposal 2 is now winning
        self.assertEqual(self.c.winner_name(), b'Trump\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00')

if __name__ == '__main__':
    unittest.main()

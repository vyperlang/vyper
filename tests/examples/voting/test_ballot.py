import pytest


@pytest.fixture
def c(get_contract):
    with open('examples/voting/ballot.vy') as f:
        contract_code = f.read()
    return get_contract(contract_code, *[[b"Clinton", b"Trump"]])


z0 = '0x0000000000000000000000000000000000000000'


def test_initial_state(w3, c):
    a0 = w3.eth.accounts[0]
    # Check chairperson is msg.sender
    assert c.chairperson() == a0
    # Check propsal names are correct
    assert c.proposals__name(0)[:7] == b'Clinton'
    assert c.proposals__name(1)[:5] == b'Trump'
    # Check proposal vote_count is 0
    assert c.proposals__vote_count(0) == 0
    assert c.proposals__vote_count(1) == 0
    # Check voter_count is 0
    assert c.voter_count() == 0
    # Check voter starts empty
    assert c.voters__delegate(z0) is None
    assert c.voters__vote(z0) == 0
    assert c.voters__voted(z0) is False
    assert c.voters__weight(z0) == 0


def test_give_the_right_to_vote(w3, c, assert_tx_failed):
    a0, a1, a2, a3, a4, a5 = w3.eth.accounts[:6]
    c.give_right_to_vote(a1, transact={})
    # Check voter given right has weight of 1
    assert c.voters__weight(a1) == 1
    # Check no other voter attributes have changed
    assert c.voters__delegate(a1) is None
    assert c.voters__vote(a1) == 0
    assert c.voters__voted(a1) is False
    # Chairperson can give themselves the right to vote
    c.give_right_to_vote(a0, transact={})
    # Check chairperson has weight of 1
    assert c.voters__weight(a0) == 1
    # Check voter_acount is 2
    assert c.voter_count() == 2
    # Check several giving rights to vote
    c.give_right_to_vote(a2, transact={})
    c.give_right_to_vote(a3, transact={})
    c.give_right_to_vote(a4, transact={})
    c.give_right_to_vote(a5, transact={})
    # Check voter_acount is now 6
    assert c.voter_count() == 6
    # Check chairperson cannot give the right to vote twice to the same voter
    assert_tx_failed(lambda: c.give_right_to_vote(a5, transact={}))
    # Check voters weight didn't change
    assert c.voters__weight(a5) == 1


def test_forward_weight(w3, c):
    a0, a1, a2, a3, a4, a5, a6, a7, a8, a9 = w3.eth.accounts[:10]
    c.give_right_to_vote(a0, transact={})
    c.give_right_to_vote(a1, transact={})
    c.give_right_to_vote(a2, transact={})
    c.give_right_to_vote(a3, transact={})
    c.give_right_to_vote(a4, transact={})
    c.give_right_to_vote(a5, transact={})
    c.give_right_to_vote(a6, transact={})
    c.give_right_to_vote(a7, transact={})
    c.give_right_to_vote(a8, transact={})
    c.give_right_to_vote(a9, transact={})

    # aN(V) in these comments means address aN has vote weight V

    c.delegate(a2, transact={'from': a1})
    # a1(0) -> a2(2)    a3(1)
    c.delegate(a3, transact={'from': a2})
    # a1(0) -> a2(0) -> a3(3)
    assert c.voters__weight(a1) == 0
    assert c.voters__weight(a2) == 0
    assert c.voters__weight(a3) == 3

    c.delegate(a9, transact={'from': a8})
    # a7(1)    a8(0) -> a9(2)
    c.delegate(a8, transact={'from': a7})
    # a7(0) -> a8(0) -> a9(3)
    assert c.voters__weight(a7) == 0
    assert c.voters__weight(a8) == 0
    assert c.voters__weight(a9) == 3
    c.delegate(a7, transact={'from': a6})
    c.delegate(a6, transact={'from': a5})
    c.delegate(a5, transact={'from': a4})
    # a4(0) -> a5(0) -> a6(0) -> a7(0) -> a8(0) -> a9(6)
    assert c.voters__weight(a9) == 6
    assert c.voters__weight(a8) == 0

    # a3(3)    a4(0) -> a5(0) -> a6(0) -> a7(0) -> a8(0) -> a9(6)
    c.delegate(a4, transact={'from': a3})
    # a3(0) -> a4(0) -> a5(0) -> a6(0) -> a7(0) -> a8(3) -> a9(6)
    # a3's vote weight of 3 only makes it to a8 in the delegation chain:
    assert c.voters__weight(a8) == 3
    assert c.voters__weight(a9) == 6

    # call forward_weight again to move the vote weight the
    # rest of the way:
    c.forward_weight(a8, transact={})
    # a3(0) -> a4(0) -> a5(0) -> a6(0) -> a7(0) -> a8(0) -> a9(9)
    assert c.voters__weight(a8) == 0
    assert c.voters__weight(a9) == 9

    # a0(1) -> a1(0) -> a2(0) -> a3(0) -> a4(0) -> a5(0) -> a6(0) -> a7(0) -> a8(0) -> a9(9)
    c.delegate(a1, transact={'from': a0})
    # a0's vote weight of 1 only makes it to a5 in the delegation chain:
    # a0(0) -> a1(0) -> a2(0) -> a3(0) -> a4(0) -> a5(1) -> a6(0) -> a7(0) -> a8(0) -> a9(9)
    assert c.voters__weight(a5) == 1
    assert c.voters__weight(a9) == 9

    # once again call forward_weight to move the vote weight the
    # rest of the way:
    c.forward_weight(a5, transact={})
    # a0(0) -> a1(0) -> a2(0) -> a3(0) -> a4(0) -> a5(0) -> a6(0) -> a7(0) -> a8(0) -> a9(10)
    assert c.voters__weight(a5) == 0
    assert c.voters__weight(a9) == 10


def test_block_short_cycle(w3, c, assert_tx_failed):
    a0, a1, a2, a3, a4, a5, a6, a7, a8, a9 = w3.eth.accounts[:10]
    c.give_right_to_vote(a0, transact={})
    c.give_right_to_vote(a1, transact={})
    c.give_right_to_vote(a2, transact={})
    c.give_right_to_vote(a3, transact={})
    c.give_right_to_vote(a4, transact={})
    c.give_right_to_vote(a5, transact={})

    c.delegate(a1, transact={'from': a0})
    c.delegate(a2, transact={'from': a1})
    c.delegate(a3, transact={'from': a2})
    c.delegate(a4, transact={'from': a3})
    # would create a length 5 cycle:
    assert_tx_failed(lambda: c.delegate(a0, transact={'from': a4}))

    c.delegate(a5, transact={'from': a4})
    # can't detect length 6 cycle, so this works:
    c.delegate(a0, transact={'from': a5})
    # which is fine for the contract; those votes are simply spoiled.
    # but this is something the frontend should prevent for user friendliness


def test_delegate(w3, c, assert_tx_failed):
    a0, a1, a2, a3, a4, a5, a6 = w3.eth.accounts[:7]
    c.give_right_to_vote(a0, transact={})
    c.give_right_to_vote(a1, transact={})
    c.give_right_to_vote(a2, transact={})
    c.give_right_to_vote(a3, transact={})
    # Voter's weight is 1
    assert c.voters__weight(a1) == 1
    # Voter can delegate: a1 -> a0
    c.delegate(a0, transact={'from': a1})
    # Voter's weight is now 0
    assert c.voters__weight(a1) == 0
    # Voter has voted
    assert c.voters__voted(a1) is True
    # Delegate's weight is 2
    assert c.voters__weight(a0) == 2
    # Voter cannot delegate twice
    assert_tx_failed(lambda: c.delegate(a2, transact={'from': a1}))
    # Voter cannot delegate to themselves
    assert_tx_failed(lambda: c.delegate(a2, transact={'from': a2}))
    # Voter CAN delegate to someone who hasn't been granted right to vote
    # Exercise: prevent that
    c.delegate(a6, transact={'from': a2})
    # Voter's delegatation is passed up to final delegate, yielding:
    # a3 -> a1 -> a0
    c.delegate(a1, transact={'from': a3})
    # Delegate's weight is 3
    assert c.voters__weight(a0) == 3


def test_vote(w3, c, assert_tx_failed):
    a0, a1, a2, a3, a4, a5, a6, a7, a8, a9 = w3.eth.accounts[:10]
    c.give_right_to_vote(a0, transact={})
    c.give_right_to_vote(a1, transact={})
    c.give_right_to_vote(a2, transact={})
    c.give_right_to_vote(a3, transact={})
    c.give_right_to_vote(a4, transact={})
    c.give_right_to_vote(a5, transact={})
    c.give_right_to_vote(a6, transact={})
    c.give_right_to_vote(a7, transact={})
    c.delegate(a0, transact={'from': a1})
    c.delegate(a1, transact={'from': a3})
    # Voter can vote
    c.vote(0, transact={})
    # Vote count changes based on voters weight
    assert c.proposals__vote_count(0) == 3
    # Voter cannot vote twice
    assert_tx_failed(lambda: c.vote(0))
    # Voter cannot vote if they've delegated
    assert_tx_failed(lambda: c.vote(0, transact={'from': a1}))
    # Several voters can vote
    c.vote(1, transact={'from': a4})
    c.vote(1, transact={'from': a2})
    c.vote(1, transact={'from': a5})
    c.vote(1, transact={'from': a6})
    assert c.proposals__vote_count(1) == 4
    # Can't vote on a non-proposal
    assert_tx_failed(lambda: c.vote(2, transact={'from': a7}))


def test_winning_proposal(w3, c):
    a0, a1, a2 = w3.eth.accounts[:3]
    c.give_right_to_vote(a0, transact={})
    c.give_right_to_vote(a1, transact={})
    c.give_right_to_vote(a2, transact={})
    c.vote(0, transact={})
    # Proposal 0 is now winning
    assert c.winning_proposal() == 0
    c.vote(1, transact={'from': a1})
    # Proposal 0 is still winning (the proposals are tied)
    assert c.winning_proposal() == 0
    c.vote(1, transact={'from': a2})
    # Proposal 2 is now winning
    assert c.winning_proposal() == 1


def test_winner_namer(w3, c):
    a0, a1, a2 = w3.eth.accounts[:3]
    c.give_right_to_vote(a0, transact={})
    c.give_right_to_vote(a1, transact={})
    c.give_right_to_vote(a2, transact={})
    c.delegate(a1, transact={'from': a2})
    c.vote(0, transact={})
    # Proposal 0 is now winning
    assert c.winner_name()[:7], b'Clinton'
    c.vote(1, transact={'from': a1})
    # Proposal 2 is now winning
    assert c.winner_name()[:5], b'Trump'

import pytest

PROPOSAL_1_NAME = b"Clinton" + b"\x00" * 25
PROPOSAL_2_NAME = b"Trump" + b"\x00" * 27


@pytest.fixture
def c(get_contract):
    with open("examples/voting/ballot.vy") as f:
        contract_code = f.read()
    return get_contract(contract_code, *[[PROPOSAL_1_NAME, PROPOSAL_2_NAME]])


z0 = "0x0000000000000000000000000000000000000000"


def test_initial_state(w3, c):
    a0 = w3.eth.accounts[0]
    # Check chairperson is msg.sender
    assert c.chairperson() == a0
    # Check propsal names are correct
    assert c.proposals(0)[0][:7] == b"Clinton"  # Proposal.name
    assert c.proposals(1)[0][:5] == b"Trump"  # Proposal.name
    # Check proposal voteCount is 0
    assert c.proposals(0)[1] == 0  # Proposal.voteCount
    assert c.proposals(1)[1] == 0  # Proposal.voteCount
    # Check voterCount is 0
    assert c.voterCount() == 0
    # Check voter starts empty
    assert c.voters(z0)[2] is None  # Voter.delegate
    assert c.voters(z0)[3] == 0  # Voter.vote
    assert c.voters(z0)[1] is False  # Voter.voted
    assert c.voters(z0)[0] == 0  # Voter.weight


def test_give_the_right_to_vote(w3, c, tx_failed):
    a0, a1, a2, a3, a4, a5 = w3.eth.accounts[:6]
    c.giveRightToVote(a1, transact={})
    # Check voter given right has weight of 1
    assert c.voters(a1)[0] == 1  # Voter.weight
    # Check no other voter attributes have changed
    assert c.voters(a1)[2] is None  # Voter.delegate
    assert c.voters(a1)[3] == 0  # Voter.vote
    assert c.voters(a1)[1] is False  # Voter.voted
    # Chairperson can give themselves the right to vote
    c.giveRightToVote(a0, transact={})
    # Check chairperson has weight of 1
    assert c.voters(a0)[0] == 1  # Voter.weight
    # Check voter_acount is 2
    assert c.voterCount() == 2
    # Check several giving rights to vote
    c.giveRightToVote(a2, transact={})
    c.giveRightToVote(a3, transact={})
    c.giveRightToVote(a4, transact={})
    c.giveRightToVote(a5, transact={})
    # Check voter_acount is now 6
    assert c.voterCount() == 6
    # Check chairperson cannot give the right to vote twice to the same voter
    with tx_failed():
        c.giveRightToVote(a5, transact={})
    # Check voters weight didn't change
    assert c.voters(a5)[0] == 1  # Voter.weight


def test_forward_weight(w3, c):
    a0, a1, a2, a3, a4, a5, a6, a7, a8, a9 = w3.eth.accounts[:10]
    c.giveRightToVote(a0, transact={})
    c.giveRightToVote(a1, transact={})
    c.giveRightToVote(a2, transact={})
    c.giveRightToVote(a3, transact={})
    c.giveRightToVote(a4, transact={})
    c.giveRightToVote(a5, transact={})
    c.giveRightToVote(a6, transact={})
    c.giveRightToVote(a7, transact={})
    c.giveRightToVote(a8, transact={})
    c.giveRightToVote(a9, transact={})

    # aN(V) in these comments means address aN has vote weight V

    c.delegate(a2, transact={"from": a1})
    # a1(0) -> a2(2)    a3(1)
    c.delegate(a3, transact={"from": a2})
    # a1(0) -> a2(0) -> a3(3)
    assert c.voters(a1)[0] == 0  # Voter.weight
    assert c.voters(a2)[0] == 0  # Voter.weight
    assert c.voters(a3)[0] == 3  # Voter.weight

    c.delegate(a9, transact={"from": a8})
    # a7(1)    a8(0) -> a9(2)
    c.delegate(a8, transact={"from": a7})
    # a7(0) -> a8(0) -> a9(3)
    assert c.voters(a7)[0] == 0  # Voter.weight
    assert c.voters(a8)[0] == 0  # Voter.weight
    assert c.voters(a9)[0] == 3  # Voter.weight
    c.delegate(a7, transact={"from": a6})
    c.delegate(a6, transact={"from": a5})
    c.delegate(a5, transact={"from": a4})
    # a4(0) -> a5(0) -> a6(0) -> a7(0) -> a8(0) -> a9(6)
    assert c.voters(a9)[0] == 6  # Voter.weight
    assert c.voters(a8)[0] == 0  # Voter.weight

    # a3(3)    a4(0) -> a5(0) -> a6(0) -> a7(0) -> a8(0) -> a9(6)
    c.delegate(a4, transact={"from": a3})
    # a3(0) -> a4(0) -> a5(0) -> a6(0) -> a7(0) -> a8(3) -> a9(6)
    # a3's vote weight of 3 only makes it to a8 in the delegation chain:
    assert c.voters(a8)[0] == 3  # Voter.weight
    assert c.voters(a9)[0] == 6  # Voter.weight

    # call forward_weight again to move the vote weight the
    # rest of the way:
    c.forwardWeight(a8, transact={})
    # a3(0) -> a4(0) -> a5(0) -> a6(0) -> a7(0) -> a8(0) -> a9(9)
    assert c.voters(a8)[0] == 0  # Voter.weight
    assert c.voters(a9)[0] == 9  # Voter.weight

    # a0(1) -> a1(0) -> a2(0) -> a3(0) -> a4(0) -> a5(0) -> a6(0) -> a7(0) -> a8(0) -> a9(9)
    c.delegate(a1, transact={"from": a0})
    # a0's vote weight of 1 only makes it to a5 in the delegation chain:
    # a0(0) -> a1(0) -> a2(0) -> a3(0) -> a4(0) -> a5(1) -> a6(0) -> a7(0) -> a8(0) -> a9(9)
    assert c.voters(a5)[0] == 1  # Voter.weight
    assert c.voters(a9)[0] == 9  # Voter.weight

    # once again call forward_weight to move the vote weight the
    # rest of the way:
    c.forwardWeight(a5, transact={})
    # a0(0) -> a1(0) -> a2(0) -> a3(0) -> a4(0) -> a5(0) -> a6(0) -> a7(0) -> a8(0) -> a9(10)
    assert c.voters(a5)[0] == 0  # Voter.weight
    assert c.voters(a9)[0] == 10  # Voter.weight


def test_block_short_cycle(w3, c, tx_failed):
    a0, a1, a2, a3, a4, a5, a6, a7, a8, a9 = w3.eth.accounts[:10]
    c.giveRightToVote(a0, transact={})
    c.giveRightToVote(a1, transact={})
    c.giveRightToVote(a2, transact={})
    c.giveRightToVote(a3, transact={})
    c.giveRightToVote(a4, transact={})
    c.giveRightToVote(a5, transact={})

    c.delegate(a1, transact={"from": a0})
    c.delegate(a2, transact={"from": a1})
    c.delegate(a3, transact={"from": a2})
    c.delegate(a4, transact={"from": a3})
    # would create a length 5 cycle:
    with tx_failed():
        c.delegate(a0, transact={"from": a4})

    c.delegate(a5, transact={"from": a4})
    # can't detect length 6 cycle, so this works:
    c.delegate(a0, transact={"from": a5})
    # which is fine for the contract; those votes are simply spoiled.
    # but this is something the frontend should prevent for user friendliness


def test_delegate(w3, c, tx_failed):
    a0, a1, a2, a3, a4, a5, a6 = w3.eth.accounts[:7]
    c.giveRightToVote(a0, transact={})
    c.giveRightToVote(a1, transact={})
    c.giveRightToVote(a2, transact={})
    c.giveRightToVote(a3, transact={})
    # Voter's weight is 1
    assert c.voters(a1)[0] == 1  # Voter.weight
    # Voter can delegate: a1 -> a0
    c.delegate(a0, transact={"from": a1})
    # Voter's weight is now 0
    assert c.voters(a1)[0] == 0  # Voter.weight
    # Voter has voted
    assert c.voters(a1)[1] is True  # Voter.voted
    # Delegate's weight is 2
    assert c.voters(a0)[0] == 2  # Voter.weight
    # Voter cannot delegate twice
    with tx_failed():
        c.delegate(a2, transact={"from": a1})
    # Voter cannot delegate to themselves
    with tx_failed():
        c.delegate(a2, transact={"from": a2})
    # Voter CAN delegate to someone who hasn't been granted right to vote
    # Exercise: prevent that
    c.delegate(a6, transact={"from": a2})
    # Voter's delegatation is passed up to final delegate, yielding:
    # a3 -> a1 -> a0
    c.delegate(a1, transact={"from": a3})
    # Delegate's weight is 3
    assert c.voters(a0)[0] == 3  # Voter.weight


def test_vote(w3, c, tx_failed):
    a0, a1, a2, a3, a4, a5, a6, a7, a8, a9 = w3.eth.accounts[:10]
    c.giveRightToVote(a0, transact={})
    c.giveRightToVote(a1, transact={})
    c.giveRightToVote(a2, transact={})
    c.giveRightToVote(a3, transact={})
    c.giveRightToVote(a4, transact={})
    c.giveRightToVote(a5, transact={})
    c.giveRightToVote(a6, transact={})
    c.giveRightToVote(a7, transact={})
    c.delegate(a0, transact={"from": a1})
    c.delegate(a1, transact={"from": a3})
    # Voter can vote
    c.vote(0, transact={})
    # Vote count changes based on voters weight
    assert c.proposals(0)[1] == 3  # Proposal.voteCount
    # Voter cannot vote twice
    with tx_failed():
        c.vote(0)
    # Voter cannot vote if they've delegated
    with tx_failed():
        c.vote(0, transact={"from": a1})
    # Several voters can vote
    c.vote(1, transact={"from": a4})
    c.vote(1, transact={"from": a2})
    c.vote(1, transact={"from": a5})
    c.vote(1, transact={"from": a6})
    assert c.proposals(1)[1] == 4  # Proposal.voteCount
    # Can't vote on a non-proposal
    with tx_failed():
        c.vote(2, transact={"from": a7})


def test_winning_proposal(w3, c):
    a0, a1, a2 = w3.eth.accounts[:3]
    c.giveRightToVote(a0, transact={})
    c.giveRightToVote(a1, transact={})
    c.giveRightToVote(a2, transact={})
    c.vote(0, transact={})
    # Proposal 0 is now winning
    assert c.winningProposal() == 0
    c.vote(1, transact={"from": a1})
    # Proposal 0 is still winning (the proposals are tied)
    assert c.winningProposal() == 0
    c.vote(1, transact={"from": a2})
    # Proposal 2 is now winning
    assert c.winningProposal() == 1


def test_winner_namer(w3, c):
    a0, a1, a2 = w3.eth.accounts[:3]
    c.giveRightToVote(a0, transact={})
    c.giveRightToVote(a1, transact={})
    c.giveRightToVote(a2, transact={})
    c.delegate(a1, transact={"from": a2})
    c.vote(0, transact={})
    # Proposal 0 is now winning
    assert c.winnerName()[:7] == b"Clinton"
    c.vote(1, transact={"from": a1})
    # Proposal 2 is now winning
    assert c.winnerName()[:5] == b"Trump"

# Voting with delegation.

# Information about voters
voters: public({
    # weight is accumulated by delegation
    weight: num,
    # if true, that person already voted
    voted: bool,
    # person delegated to
    delegate: address,
    # index of the voted proposal
    vote: num
}[address])

# This is a type for a list of proposals.
proposals: public({
    # short name (up to 32 bytes)
    name: bytes32,
    # number of accumulated votes
    vote_count: num
}[num])

voter_count: public(num)
chairperson: public(address)

# Setup global variables
def __init__(_proposalNames: bytes32[2]):
    self.chairperson = msg.sender
    self.voter_count = 0
    for i in range(2):
        self.proposals[i] = {
            name: _proposalNames[i],
            vote_count: 0
        }

# Give `voter` the right to vote on this ballot.
# May only be called by `chairperson`.
def give_right_to_vote(voter: address):
    # Throws if sender is not chairpers
    assert msg.sender == self.chairperson
    # Throws if voter has already voted
    assert not self.voters[voter].voted
    # Throws if voters voting weight isn't 0 
    assert self.voters[voter].weight == 0
    self.voters[voter].weight = 1
    self.voter_count += 1

# Delegate your vote to the voter `to`.
def delegate(_to: address):
    to = _to
    # Throws if sender has already voted
    assert not self.voters[msg.sender].voted 
    # Throws if sender tries to delegate their vote to themselves
    assert not msg.sender == to
    # loop can delegate votes up to the current voter count
    for i in range(self.voter_count, self.voter_count+1):
        if self.voters[to].delegate:
        # Because there are not while loops, use recursion to forward the delegation
        # self.delegate(self.voters[to].delegate)
            assert self.voters[to].delegate != msg.sender 
            to = self.voters[to].delegate
    self.voters[msg.sender].voted = True
    self.voters[msg.sender].delegate = to
    if self.voters[to].voted:
        # If the delegate already voted,
        # directly add to the number of votes
        self.proposals[self.voters[to].vote].vote_count += self.voters[msg.sender].weight
    else:
        # If the delegate did not vote yet,
        # add to her weight.
        self.voters[to].weight += self.voters[msg.sender].weight

# Give your vote (including votes delegated to you)
# to proposal `proposals[proposal].name`.
def vote(proposal: num):
    assert not  self.voters[msg.sender].voted
    self.voters[msg.sender].voted = True
    self.voters[msg.sender].vote = proposal
    # If `proposal` is out of the range of the array,
    # this will throw automatically and revert all
    # changes.
    self.proposals[proposal].vote_count += self.voters[msg.sender].weight

# Computes the winning proposal taking all
# previous votes into account.
@constant
def winning_proposal() -> num:
    winning_vote_count = 0
    for i in range(5):
        if self.proposals[i].vote_count > winning_vote_count:
            winning_vote_count = self.proposals[i].vote_count
            winning_proposal = i
    return winning_proposal

# Calls winning_proposal() function to get the index
# of the winner contained in the proposals array and then
# returns the name of the winner
@constant
def winner_name() -> bytes32:
    return self.proposals[self.winning_proposal()].name

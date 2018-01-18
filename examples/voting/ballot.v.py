# Voting with delegation.

# Information about voters
voters: public({
    # weight is accumulated by delegation
    weight: num,
    # if true, that person already voted (which includes voting by delegating)
    voted: bool,
    # person delegated to
    delegate: address,
    # index of the voted proposal, which is not meaningful unless `voted` is True.
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
num_proposals: public(num)

@public
@constant
def delegated(addr: address) -> bool:
    # equivalent to  
        # self.voters[addr].delegate != 0x0000000000000000000000000000000000000000
    return not not self.voters[addr].delegate

@public
@constant
def directly_voted(addr: address) -> bool:
    # not <address> equivalent to 
        # <address> == 0x0000000000000000000000000000000000000000
    return self.voters[addr].voted and not self.voters[addr].delegate

# Setup global variables
@public
def __init__(_proposalNames: bytes32[2]):
    self.chairperson = msg.sender
    self.voter_count = 0
    for i in range(2):
        self.proposals[i] = {
            name: _proposalNames[i],
            vote_count: 0
        }
        self.num_proposals += 1

# Give a `voter` the right to vote on this ballot.
# This may only be called by the `chairperson`.
@public
def give_right_to_vote(voter: address):
    # Throws if the sender is not the chairperson.
    assert msg.sender == self.chairperson
    # Throws if the voter has already voted.
    assert not self.voters[voter].voted
    # Throws if the voter's voting weight isn't 0.
    assert self.voters[voter].weight == 0
    self.voters[voter].weight = 1
    self.voter_count += 1

# Used by `delegate` below, and can be called by anyone.
@public
def forward_weight(delegate_with_weight_to_forward: address):
    assert self.delegated(delegate_with_weight_to_forward)
    # Throw if there is nothing to do:
    assert self.voters[delegate_with_weight_to_forward].weight > 0

    target: address = self.voters[delegate_with_weight_to_forward].delegate
    for i in range(4):
        if self.delegated(target):
            target = self.voters[target].delegate
            # The following effectively detects cycles of length <= 5,
            # in which the delegation is given back to the delegator.
            # This could be done for any number of loops,
            # or even infinitely with a while loop.
            # However, cycles aren't actually problematic for correctness;
            # they just result in spoiled votes.
            # So, in the production version, this should instead be
            # the responsibility of the contract's client, and this
            # check should be removed.
            assert target != delegate_with_weight_to_forward
        else:
            # Weight will be moved to someone who directly voted or
            # hasn't voted.
            break

    weight_to_forward: num = self.voters[delegate_with_weight_to_forward].weight
    self.voters[delegate_with_weight_to_forward].weight = 0
    self.voters[target].weight += weight_to_forward

    if self.directly_voted(target):
        self.proposals[self.voters[target].vote].vote_count += weight_to_forward
        self.voters[target].weight = 0

    # To reiterate: if target is also a delegate, this function will need
    # to be called again, similarly to as above.

# Delegate your vote to the voter `to`.
@public
def delegate(to: address):
    # Throws if the sender has already voted
    assert not self.voters[msg.sender].voted
    # Throws if the sender tries to delegate their vote to themselves or to
    # the default address value of 0x0000000000000000000000000000000000000000
    # (the latter might not be problematic, but I don't want to think about it).
    assert to != msg.sender and not not to

    self.voters[msg.sender].voted = True
    self.voters[msg.sender].delegate = to

    # This call will throw if and only if this delegation would cause a loop 
        # of length <= 5 that ends up delegating back to the delegator.
    self.forward_weight(msg.sender)

# Give your vote (including votes delegated to you)
# to proposal `proposals[proposal].name`.
@public
def vote(proposal: num):
    # can't vote twice
    assert not self.voters[msg.sender].voted
    # can only vote on legitimate proposals
    assert proposal < self.num_proposals
    
    self.voters[msg.sender].vote = proposal
    self.voters[msg.sender].voted = True

    # transfer msg.sender's weight to proposal
    self.proposals[proposal].vote_count += self.voters[msg.sender].weight
    self.voters[msg.sender].weight = 0

# Computes the winning proposal taking all
# previous votes into account.
@public
@constant
def winning_proposal() -> num:
    winning_vote_count: num = 0
    winning_proposal: num = 0
    for i in range(2):
        if self.proposals[i].vote_count > winning_vote_count:
            winning_vote_count = self.proposals[i].vote_count
            winning_proposal = i
    return winning_proposal

# Calls winning_proposal() function to get the index
# of the winner contained in the proposals array and then
# returns the name of the winner
@public
@constant
def winner_name() -> bytes32:
    return self.proposals[self.winning_proposal()].name

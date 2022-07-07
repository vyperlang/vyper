# Voting with delegation.

# Information about voters
struct Voter:
    # weight is accumulated by delegation
    weight: int128
    # if true, that person already voted (which includes voting by delegating)
    voted: bool
    # person delegated to
    delegate: address
    # index of the voted proposal, which is not meaningful unless `voted` is True.
    vote: int128

# Users can create proposals
struct Proposal:
    # short name (up to 32 bytes)
    name: bytes32
    # number of accumulated votes
    vote_count: int128

voters: public(HashMap[address, Voter])
proposals: public(HashMap[int128, Proposal])
voter_count: public(int128)
chairperson: public(address)
int128_proposals: public(int128)


@view
@internal
def _delegated(addr: address) -> bool:
    return self.voters[addr].delegate != ZERO_ADDRESS


@view
@external
def delegated(addr: address) -> bool:
    return self._delegated(addr)


@view
@internal
def _directly_voted(addr: address) -> bool:
    return self.voters[addr].voted and (self.voters[addr].delegate == ZERO_ADDRESS)


@view
@external
def directly_voted(addr: address) -> bool:
    return self._directly_voted(addr)


# Setup global variables
@external
def __init__(proposal_names: bytes32[2]):
    self.chairperson = msg.sender
    self.voter_count = 0
    for i in range(2):
        self.proposals[i] = Proposal({
            name: proposal_names[i],
            vote_count: 0
        })
        self.int128_proposals += 1

# Give a `voter` the right to vote on this ballot.
# This may only be called by the `chairperson`.
@external
def give_right_to_vote(voter: address):
    # Throws if the sender is not the chairperson.
    assert msg.sender == self.chairperson
    # Throws if the voter has already voted.
    assert not self.voters[voter].voted
    # Throws if the voter's voting weight isn't 0.
    assert self.voters[voter].weight == 0
    self.voters[voter].weight = 1
    self.voter_count += 1

# Used by `delegate` below, callable externally via `forward_weight`
@internal
def _forward_weight(delegate_with_weight_to_forward: address):
    assert self._delegated(delegate_with_weight_to_forward)
    # Throw if there is nothing to do:
    assert self.voters[delegate_with_weight_to_forward].weight > 0

    target: address = self.voters[delegate_with_weight_to_forward].delegate
    for i in range(4):
        if self._delegated(target):
            target = self.voters[target].delegate
            # The following effectively detects cycles of length <= 5,
            # in which the delegation is given back to the delegator.
            # This could be done for any int128ber of loops,
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

    weight_to_forward: int128 = self.voters[delegate_with_weight_to_forward].weight
    self.voters[delegate_with_weight_to_forward].weight = 0
    self.voters[target].weight += weight_to_forward

    if self._directly_voted(target):
        self.proposals[self.voters[target].vote].vote_count += weight_to_forward
        self.voters[target].weight = 0

    # To reiterate: if target is also a delegate, this function will need
    # to be called again, similarly to as above.

# Public function to call _forward_weight
@external
def forward_weight(delegate_with_weight_to_forward: address):
    self._forward_weight(delegate_with_weight_to_forward)

# Delegate your vote to the voter `to`.
@external
def delegate(to: address):
    # Throws if the sender has already voted
    assert not self.voters[msg.sender].voted
    # Throws if the sender tries to delegate their vote to themselves or to
    # the default address value of 0x0000000000000000000000000000000000000000
    # (the latter might not be problematic, but I don't want to think about it).
    assert to != msg.sender
    assert to != ZERO_ADDRESS

    self.voters[msg.sender].voted = True
    self.voters[msg.sender].delegate = to

    # This call will throw if and only if this delegation would cause a loop
        # of length <= 5 that ends up delegating back to the delegator.
    self._forward_weight(msg.sender)

# Give your vote (including votes delegated to you)
# to proposal `proposals[proposal].name`.
@external
def vote(proposal: int128):
    # can't vote twice
    assert not self.voters[msg.sender].voted
    # can only vote on legitimate proposals
    assert proposal < self.int128_proposals

    self.voters[msg.sender].vote = proposal
    self.voters[msg.sender].voted = True

    # transfer msg.sender's weight to proposal
    self.proposals[proposal].vote_count += self.voters[msg.sender].weight
    self.voters[msg.sender].weight = 0

# Computes the winning proposal taking all
# previous votes into account.
@view
@internal
def _winning_proposal() -> int128:
    winning_vote_count: int128 = 0
    winning_proposal: int128 = 0
    for i in range(2):
        if self.proposals[i].vote_count > winning_vote_count:
            winning_vote_count = self.proposals[i].vote_count
            winning_proposal = i
    return winning_proposal

@view
@external
def winning_proposal() -> int128:
    return self._winning_proposal()


# Calls winning_proposal() function to get the index
# of the winner contained in the proposals array and then
# returns the name of the winner
@view
@external
def winner_name() -> bytes32:
    return self.proposals[self._winning_proposal()].name

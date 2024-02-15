#pragma version >0.3.10

###########################################################################
## THIS IS EXAMPLE CODE, NOT MEANT TO BE USED IN PRODUCTION! CAVEAT EMPTOR!
###########################################################################

# example of a crowd funding contract

funders: HashMap[address, uint256]
beneficiary: address
deadline: public(uint256)
goal: public(uint256)
timelimit: public(uint256)

# Setup global variables
@deploy
def __init__(_beneficiary: address, _goal: uint256, _timelimit: uint256):
    self.beneficiary = _beneficiary
    self.deadline = block.timestamp + _timelimit
    self.timelimit = _timelimit
    self.goal = _goal

# Participate in this crowdfunding campaign
@external
@payable
def participate():
    assert block.timestamp < self.deadline, "deadline has expired"

    self.funders[msg.sender] += msg.value

# Enough money was raised! Send funds to the beneficiary
@external
def finalize():
    assert block.timestamp >= self.deadline, "deadline has not expired yet"
    assert self.balance >= self.goal, "goal has not been reached"

    selfdestruct(self.beneficiary)

# Let participants withdraw their fund
@external
def refund():
    assert block.timestamp >= self.deadline and self.balance < self.goal
    assert self.funders[msg.sender] > 0

    value: uint256 = self.funders[msg.sender]
    self.funders[msg.sender] = 0

    send(msg.sender, value)

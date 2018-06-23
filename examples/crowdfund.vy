# Setup private variables (only callable from within the contract)
funders: {sender: address, value: wei_value}[int128]
nextFunderIndex: int128
beneficiary: address
deadline: timestamp
goal: wei_value
refundIndex: int128
timelimit: timedelta


# Setup global variables
@public
def __init__(_beneficiary: address, _goal: wei_value, _timelimit: timedelta):
    self.beneficiary = _beneficiary
    self.deadline = block.timestamp + _timelimit
    self.timelimit = _timelimit
    self.goal = _goal


# Participate in this crowdfunding campaign
@public
@payable
def participate():
    assert block.timestamp < self.deadline

    nfi: int128 = self.nextFunderIndex

    self.funders[nfi] = {sender: msg.sender, value: msg.value}
    self.nextFunderIndex = nfi + 1


# Enough money was raised! Send funds to the beneficiary
@public
def finalize():
    assert block.timestamp >= self.deadline and self.balance >= self.goal

    selfdestruct(self.beneficiary)


# Not enough money was raised! Refund everyone (max 30 people at a time
# to avoid gas limit issues)
@public
def refund():
    assert block.timestamp >= self.deadline and self.balance < self.goal

    ind: int128 = self.refundIndex

    for i in range(ind, ind + 30):
        if i >= self.nextFunderIndex:
            self.refundIndex = self.nextFunderIndex
            return

        send(self.funders[i].sender, self.funders[i].value)
        self.funders[i] = None

    self.refundIndex = ind + 30

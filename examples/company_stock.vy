stockholders: {account: address, value: wei_value}[num]
stockholderLen: num
company: address
num_shares: num
price: decimal

# Setup company
def __init__(_company: address, _num_shares: num, _inital_price: decimal):
    self.company = _company
    self.num_shares = _num_shares
    self.price = _initial_price
    self.stockholderLen = 0

@payable
def buy_stock():
    slen = self.stockholderLen
    if msg.sender not in stockholders{address}:
        self.stockholders[slen] = {account: msg.sender, value: msg.value}
        self.stockholderLen += 1
    else:
        self.stockholders{account==msg.sender} += msg.value

def sell_stock():

# Own shares of a company!
company: address
avail_shares: num
stockholders: {account: address, stock: num}[num]
num_accounts: num

price: wei_value

# Setup company
def __init__(_company: address, total_shares: num, initial_price: wei_value):
    assert total_shares > 0
    
    self.company = _company
    self.avail_shares = total_shares
    self.num_accounts = 0
    
    self.price = initial_price

@payable
def buy_stock():
    buy_order = msg.value / self.price # round_down to nearest whole num
    assert self.avail_shares >= buy_order
    
    buy_value = buy_order * self.price
    send(self.company, buy_value)
    
    # Find (or create) shareholder account
    # Take the shares off the market and give to that account
    self.avail_shares -= buy_order
    if self.num_accounts > 0:
        for i in range(self.num_accounts):
            if msg.sender == stockholders[i].account:
                self.stockholders[i].stock += buy_order
                return
    
    # Not in stockholders list, so add
    self.num_accounts += 1
    self.stockholders[self.num_accounts] = {account: msg.sender, stock: buy_order}

@payable
def sell_stock():
    sell_order = msg.value / self.price # round_down
    
    if self.num_accounts > 0:
        for i in range(self.num_accounts):
            if msg.sender == stockholders[i].account:
                if stockholders[i].stock > sell_order:
                    self.stockholders[i].stock -= sell_order
                    send(msg.sender, sell_order * self.price)
                    self.avail_shares += sell_order
                else:
                    all_stock = self.stockholders[i].stock
                    self.stockholders[i].stock = 0
                    send(msg.sender, all_stock * self.price)
                    self.avail_shares += all_stock

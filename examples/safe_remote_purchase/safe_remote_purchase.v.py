#Safe Remote Purchase (https://github.com/ethereum/solidity/blob/develop/docs/solidity-by-example.rst) ported to viper and optimized

#Rundown of the transaction:
#1. Seller posts item for sale and posts safety deposit of double the item value. Balance is 2*value.
#(1.1. Seller can reclaim deposit and close the sale as long as nothing was purchased.)
#2. Buyer purchases item (value) plus posts an additional safety deposit (Item value). Balance is 4*value
#3. Seller ships item
#4. Buyer confirms receiving the item. Buyer's deposit (value) is returned. Seller's deposit (2*value) + items value is returned. Balance is 0.

value: public(wei_value) #Value of the item
seller: public(address)
buyer: public(address)

@constant
def unlocked() -> bool: #Is a refund possible for the seller?
    return (self.balance == self.value*2)
    
@payable
def __init__():
    self.value = msg.value / 2 #Seller initializes contract by posting a safety deposit of 2*value of the item up for sale
    self.seller = msg.sender
    
def abort():
    assert self.unlocked() == true #Is the contract still refundable
    assert msg.sender == self.seller #Only seller can refund his deposit before any buyer purchases the item
    selfdestruct(self.seller) #Refunds seller, deletes contract

@payable
def purchase():
    assert self.unlocked() == true #Contract still open (item still up for sale)?
    assert msg.value == (2*self.value) #Is the deposit of correct value?
    self.buyer = msg.sender
    
def recieved():
    assert self.unlocked() == false #Is the item already purchased and pending confirmation of buyer
    assert msg.sender == self.buyer 
    send(self.buyer, self.value) #Return deposit (=value) to buyer
selfdestruct(self.seller) #Returns deposit (=2*value) and the purchase price (=value)

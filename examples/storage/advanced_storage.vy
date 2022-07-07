event DataChange:
    setter: indexed(address)
    value: int128

stored_data: public(int128)

@external
def __init__(x: int128):
  self.stored_data = x

@external
def set(x: int128):
  assert x >= 0, "No negative values"
  assert self.stored_data < 100, "Storage is locked when 100 or more is stored"
  self.stored_data = x
  log DataChange(msg.sender, x)

@external
def reset():
  self.stored_data = 0

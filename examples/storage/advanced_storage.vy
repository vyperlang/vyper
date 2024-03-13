#pragma version >0.3.10

event DataChange:
    setter: indexed(address)
    value: int128

storedData: public(int128)

@deploy
def __init__(_x: int128):
  self.storedData = _x

@external
def set(_x: int128):
  assert _x >= 0, "No negative values"
  assert self.storedData < 100, "Storage is locked when 100 or more is stored"
  self.storedData = _x
  log DataChange(msg.sender, _x)

@external
def reset():
  self.storedData = 0

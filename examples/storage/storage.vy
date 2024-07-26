#pragma version >0.3.10

storedData: public(int128)

@deploy
def __init__(_x: int128):
  self.storedData = _x

@external
def set(_x: int128):
  self.storedData = _x

storedData: public(int128)

@external
def __init__(_x: int128):
  self.storedData = _x

@external
def set(_x: int128):
  self.storedData = _x
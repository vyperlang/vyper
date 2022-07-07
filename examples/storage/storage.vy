stored_data: public(int128)

@external
def __init__(x: int128):
  self.stored_data = x

@external
def set(x: int128):
  self.stored_data = x

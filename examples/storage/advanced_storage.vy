DataChange: event({_setter: indexed(address), _value: int128})

storedData: public(int128)

@public
def __init__(_x: int128):
  self.storedData = _x

@public
def set(_x: int128):
  assert _x >= 0, "No negative values"
  assert self.storedData < 100, "Storage is locked when 100 or more is stored"
  self.storedData = _x
  log.DataChange(msg.sender, _x)

@public
def reset():
  self.storedData = 0

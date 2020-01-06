contract Token:
    def transfer(_to: address, _amt: uint256) -> bool: modifying
    def transferFrom(_from: address, _to: address, _amt: uint256) -> bool: modifying


contract Factory:
    def register(): modifying


token: public(address)
factory: address


@public
def __init__(_token: address, _factory: address):
    self.token = _token
    self.factory = _factory


@public
def initialize():
    # Anyone can safely call this function because of EXTCODEHASH
    Factory(self.factory).register()


@public
def receive(_from: address, _amt: uint256):
    success: bool = Token(self.token).transferFrom(_from, self, _amt)
    assert success


@public
def transfer(_to: address, _amt: uint256):
    success: bool = Token(self.token).transfer(_to, _amt)
    assert success

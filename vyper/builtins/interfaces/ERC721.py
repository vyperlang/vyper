interface_code = """
# Events

event Transfer:
    _from: address
    _to: address
    _tokenId: uint256

event Approval:
    _owner: address
    _approved: address
    _tokenId: uint256

event ApprovalForAll:
    _owner: address
    _operator: address
    _approved: bool

# Functions

@view
@external
def supportsInterface(interface_id: bytes4) -> bool:
    pass

@view
@external
def balanceOf(_owner: address) -> uint256:
    pass

@view
@external
def ownerOf(_tokenId: uint256) -> address:
    pass

@view
@external
def getApproved(_tokenId: uint256) -> address:
    pass

@view
@external
def isApprovedForAll(_owner: address, _operator: address) -> bool:
    pass

@external
@payable
def transferFrom(_from: address, _to: address, _tokenId: uint256):
    pass

@external
@payable
def safeTransferFrom(_from: address, _to: address, _tokenId: uint256):
    pass

@external
@payable
def safeTransferFrom(_from: address, _to: address, _tokenId: uint256, _data: Bytes[1024]):
    pass

@external
@payable
def approve(_approved: address, _tokenId: uint256):
    pass

@external
def setApprovalForAll(_operator: address, _approved: bool):
    pass

"""

interface_code = """
# Events

Transfer: event({_from: address, _to: address, _tokenId: uint256})
Approval: event({_owner: address, _approved: address, _tokenId: uint256})
ApprovalForAll: event({_owner: address, _operator: address, _approved: bool})

# Functions

@constant
@public
def supportsInterface(_interfaceID: bytes32) -> bool:
    pass

@constant
@public
def balanceOf(_owner: address) -> uint256:
    pass

@constant
@public
def ownerOf(_tokenId: uint256) -> address:
    pass

@constant
@public
def getApproved(_tokenId: uint256) -> address:
    pass

@constant
@public
def isApprovedForAll(_owner: address, _operator: address) -> bool:
    pass

@public
def transferFrom(_from: address, _to: address, _tokenId: uint256):
    pass

@public
def safeTransferFrom(_from: address, _to: address, _tokenId: uint256, _data: bytes[1024]):
    pass

@public
def safeTransferFrom(_from: address, _to: address, _tokenId: uint256, _data: bytes[1024]):
    pass

@public
def approve(_approved: address, _tokenId: uint256):
    pass

@public
def setApprovalForAll(_operator: address, _approved: bool):
    pass

"""

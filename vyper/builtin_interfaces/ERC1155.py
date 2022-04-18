interface_code = """
# Events

event Paused:
    account: address

event unPaused:
    account: address

event OwnershipTransferred:
    previouwOwner: address 
    newOwner: address

event TransferSingle:
    operator:   indexed(address)
    fromAddress: indexed(address)
    to: indexed(address)
    id: uint256
    value: uint256

event TransferBatch:
    operator: indexed(address) # indexed
    fromAddress: indexed(address)
    to: indexed(address)
    ids: DynArray[uint256, BATCH_SIZE]
    values: DynArray[uint256, BATCH_SIZE]

event ApprovalForAll:
    account: indexed(address)
    operator: indexed(address)
    approved: bool

# Functions

@external
def pause():
    pass

@external
def unpause():
    pass

@external
def isOwner() -> bool:
    pass

@external
def transferOwnership(newOwner: address):
    pass

@external
def renounceOwnership():
    pass

@view
@external
def balanceOf(account: address, id: uint256) -> uint256:
    pass

@external
@view
def balanceOfBatch(accounts: DynArray[address, BATCH_SIZE], ids: DynArray[uint256, BATCH_SIZE]) -> DynArray[uint256,BATCH_SIZE]:  #uint256[BATCH_SIZE]:
    pass

@external
def mint(receiver: address, id: uint256, amount:uint256, data:bytes32):
    pass

@external
def mintBatch(receiver: address, ids: DynArray[uint256, BATCH_SIZE], amounts: DynArray[uint256, BATCH_SIZE], data: bytes32):
    pass

@external
def burn(id: uint256, amount: uint256):
    pass
    
@external
def burnBatch(ids: DynArray[uint256, BATCH_SIZE], amounts: DynArray[uint256, BATCH_SIZE]):
    pass

@external
def setApprovalForAll(owner: address, operator: address, approved: bool):
    pass

@external 
@view
def isApprovedForAll(account: address, operator: address) -> bool:
    pass

@external
def safeTransferFrom(sender: address, receiver: address, id: uint256, amount: uint256, bytes: bytes32):
    pass

@external
def safeBatchTransferFrom(sender: address, receiver: address, ids: DynArray[uint256, BATCH_SIZE], amounts: DynArray[uint256, BATCH_SIZE], _bytes: bytes32):
        pass

@external
def setURI(uri: String[MAX_URI_LENGTH]):
    pass

@pure
@external
def supportsInterface(interfaceId: bytes4) -> bool:
    pass

"""

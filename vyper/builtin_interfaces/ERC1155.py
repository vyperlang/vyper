interface_code = """
# Events

event TransferSingle:
    operator: indexed(address)
    sender: indexed(address)
    receiver: indexed(address)
    id: uint256
    value: uint256

event TransferBatch:
    operator: indexed(address) # indexed
    sender: indexed(address)
    receiver: indexed(address)
    ids: DynArray[uint256, BATCH_SIZE]
    values: DynArray[uint256, BATCH_SIZE]

event ApprovalForAll:
    owner: indexed(address)
    operator: indexed(address)
    approved: bool

# Functions
@view
@external
def balanceOf(account: address, id: uint256) -> uint256:
    pass

@external
@view
def balanceOfBatch(accounts: DynArray[address, BATCH_SIZE], ids: DynArray[uint256, BATCH_SIZE]) -> DynArray[uint256, BATCH_SIZE]:
    pass

@external
def setApprovalForAll(owner: address, operator: address, approved: bool):
    pass

@external 
@view
def isApprovedForAll(account: address, operator: address) -> bool:
    pass

@external
def safeTransferFrom(sender: address, receiver: address, id: uint256, amount: uint256, data: Bytes[DATA_LENGTH]):
    pass

@external
def safeBatchTransferFrom(
    sender: address,
    receiver: address,
    ids: DynArray[uint256, BATCH_SIZE],
    amounts: DynArray[uint256, BATCH_SIZE],
    data: Bytes[DATA_LENGTH],
):
        pass

@view
@external
def URI() -> String[MAX_URI_LENGTH]:
    pass
"""

# @version >=0.3.2

# @dev Implementation of ERC-1155 non-fungible token standard
# @dev ownable, with approval, OPENSEA compatible (name, symbol)
# @author Dr. Pixel (github: @Doc-Pixel)

############### imports ###############
from vyper.interfaces import ERC165

############### variables ###############
# maximum items in a batch call. Set to 128, to be determined what the practical limits are.
BATCH_SIZE: constant(uint256) = 128             

# URI length set to 1024. 
MAX_URI_LENGTH: constant(uint256) = 1024        

# the contract owner
owner: public(address)                          

# pause status True / False
paused: public(bool)                            

# the contracts URI to find the metadata
uri: public(String[MAX_URI_LENGTH])                     

# NFT marketplace compatibility
name: public(String[1024])
symbol: public(String[1024])

# Interface IDs
ERC165_INTERFACE_ID: constant(bytes4)  = 0x01ffc9a7
ERC1155_INTERFACE_ID: constant(bytes4) = 0xd9b67a26
ERC1155_INTERFACE_ID_METADATA: constant(bytes4) = 0x0e89341c

# mappings
supportsInterfaces: constant(bytes4[3]) = [ERC165_INTERFACE_ID, ERC1155_INTERFACE_ID, ERC1155_INTERFACE_ID_METADATA]

# Mapping from token ID to account balances
balances: HashMap[uint256,HashMap[address, uint256]]            

# Mapping from account to operator approvals
operatorApprovals: HashMap[address, HashMap[address, bool]]     



############### events ###############
event Paused:
    # @dev Emits a pause event with the address that paused the contract
    account: address

event unPaused:
    # @dev Emits an unpause event with the address that paused the contract
    account: address

event OwnershipTransferred:
    # @dev Emits smart contract ownership transfer
    # @param previousOwner The current, soon to be previous owner of the contract
    # @param newOwner The new owner of the contract
    previouwOwner: address 
    newOwner: address

event TransferSingle:
    # @dev Emits on transfer of a single token
    # @param operator the address initiating the transfer. owner or authorized operator
    # @param fromAddress the address sending the token
    # @param to the address receiving the token
    # @param id the token ID
    # @param value the amount of tokens
    operator:   indexed(address)
    fromAddress: indexed(address)
    to: indexed(address)
    id: uint256
    value: uint256

event TransferBatch:
    # @dev Emits on batch transfer of tokens. the ids array correspond with the values array by their position
    # @param operator the address initiating the transfer. owner or authorized operator
    # @param fromAddress the address sending the token
    # @param to the address receiving the token
    # @param ids list of token ids
    # @param values list of amounts for each token 
    operator: indexed(address) # indexed
    fromAddress: indexed(address)
    to: indexed(address)
    ids: DynArray[uint256, BATCH_SIZE]
    values: DynArray[uint256, BATCH_SIZE]

event ApprovalForAll:
    # @dev This emits when an operator is enabled or disabled for an owner. The operator can manage
    # @dev all NFTs of the owner.
    # @param account Owner of NFT.
    # @param operator Address to which we are setting operator rights.
    # @param approved Status of operator rights(true if operator rights are given and false if revoked).
    account: indexed(address)
    operator: indexed(address)
    approved: bool

############### interfaces ###############
implements: ERC165

interface IERC1155Receiver:
    def onERC1155Received(operator: address, fromAddress: address, to: address, id: uint256, _value: uint256, data: bytes32) -> bytes32: payable
    def onERC1155BatchReceived(operator: address, fromAddress: address, to: address, _ids: DynArray[uint256, BATCH_SIZE], _amounts: DynArray[uint256, BATCH_SIZE], data: bytes32) -> bytes32: payable

interface IERC1155MetadataURI:
    def uri(id: uint256) -> String[MAX_URI_LENGTH]: payable

############### functions ###############

@external
def __init__(name: String[1024], symbol: String[1024], uri: String[1024]):
    # @dev contract initialization on deployment
    # @dev will set name and symbol, interfaces, owner and URI
    # @param name the smart contract name
    # @param symbol the smart contract symbol
    # @param uri the new uri for the contract
    self.name = name
    self.symbol = symbol
    self.paused = False 
    self.owner = msg.sender
    self.uri = uri

## contract status ##
@external
def pause():
    # @dev Pause the contract, checks if the caller is the owner and if the contract is paused already
    # @dev emits a pause event 
    assert self.owner == msg.sender, "Ownable: caller is not the owner"
    assert not self.paused, " the contract is already paused"
    self.paused = True
    log Paused(msg.sender)

@external
def unpause():
    # @dev Unpause the contract, checks if the caller is the owner and if the contract is paused already
    # @dev emits an unpause event 
    assert self.owner == msg.sender, "Ownable: caller is not the owner"
    assert self.paused, "the contract is not paused"
    self.paused = False
    log unPaused(msg.sender)

## ownership ##
@external
def isOwner() -> bool:
    # @dev if the calling user it the owner, return true. Otherwise false
    return self.owner == msg.sender

@external
def transferOwnership(newOwner: address):
    # @dev Transfer the ownership. Checks for contract pause status, current owner and prevent transferring to
    # @dev zero address
    # @dev emits an OwnershipTransferred event with the old and new owner addresses
    # @param newOwner The address of the new owner.
    assert not self.paused, "The contract has been paused"
    assert self.owner == msg.sender, "Ownable: caller is not the owner"
    assert newOwner != self.owner, "This account already owns the contract"
    assert newOwner != ZERO_ADDRESS, "Transfer to ZERO_ADDRESS not allowed. Use renounceOwnership() instead."
    oldOwner: address = self.owner
    self.owner = newOwner
    log OwnershipTransferred(oldOwner, newOwner)

@external
def renounceOwnership():
    # @dev Transfer the ownership to ZERO_ADDRESS, this will lock the contract
    # @dev emits an OwnershipTransferred event with the old and new ZERO_ADDRESS owner addresses
    assert not self.paused, "The contract has been paused"
    assert self.owner == msg.sender, "Ownable: caller is not the owner"
    oldOwner: address = self.owner
    self.owner = ZERO_ADDRESS
    log OwnershipTransferred(oldOwner, ZERO_ADDRESS)

## balance ##
@external
def balanceOf(account: address, id: uint256) -> uint256:
    # @dev check the balance for a specific ID and address
    # @dev will return the balance if the id is owned by the address
    # @dev Can also be used to check ownership of an ID
    # @param account the address to check the balance for
    # @param id the token ID to check the balance
    assert account != ZERO_ADDRESS, "Please enter a valid address"
    return self.balances[id][account]

@external
def balanceOfBatch(accounts: DynArray[address, BATCH_SIZE], ids: DynArray[uint256, BATCH_SIZE]) -> DynArray[uint256,BATCH_SIZE]:  #uint256[BATCH_SIZE]:
    # @dev check the balance for an array of specific IDs and addresses
    # @dev will return an array of balances
    # @dev Can also be used to check ownership of an ID
    # @param accounts a dynamic array of the addresses to check the balance for
    # @param ids a dynamic array of the token IDs to check the balance
    assert len(accounts) == len(ids), "ERC1155: accounts and ids length mismatch"
    batchBalances: DynArray[uint256, BATCH_SIZE] = empty(DynArray[uint256,BATCH_SIZE])
    j: uint256 = 0
    for i in ids:
        tempBalance: uint256 = self.balances[i][accounts[j]]
        batchBalances.append(tempBalance)
        j += 1
    return batchBalances

## mint ##
@external
def mint(receiver: address, id: uint256, amount:uint256, data:bytes32):
    # @dev mint one new token with a certain ID
    # @dev this can be a new token or "topping up" the balance of a non-fungible token ID
    # @param receiver the account that will receive the minted token
    # @param id the ID of the token
    # @param amount of tokens for this ID
    # @param data the data associated with this mint. Usually stays empty
    assert not self.paused, "The contract has been paused"
    assert self.owner == msg.sender, "Only the contract owner can mint"
    assert receiver != ZERO_ADDRESS, "Can not mint to ZERO ADDRESS"
    operator:address = msg.sender
    self.balances[id][receiver] += amount
    log TransferSingle(operator, ZERO_ADDRESS, receiver, id, amount)


@external
def mintBatch(receiver: address, ids: DynArray[uint256, BATCH_SIZE], amounts: DynArray[uint256, BATCH_SIZE], data: bytes32):
    # @dev mint a batch of new tokens with the passed IDs
    # @dev this can be new tokens or "topping up" the balance of existing non-fungible token IDs in the contract
    # @param receiver the account that will receive the minted token
    # @param ids array of ids for the tokens
    # @param amounts amounts of tokens for each ID in the ids array
    # @param data the data associated with this mint. Usually stays empty
    assert not self.paused, "The contract has been paused"
    assert self.owner == msg.sender, "Only the contract owner can mint"
    assert receiver != ZERO_ADDRESS, "Can not mint to ZERO ADDRESS"
    assert len(ids) == len(amounts), "ERC1155: ids and amounts length mismatch"
    operator: address = msg.sender
    
    for i in range(BATCH_SIZE):
        if i >= len(ids):
            break
        self.balances[ids[i]][receiver] = amounts[i]
    
    log TransferBatch(operator, ZERO_ADDRESS, receiver, ids, amounts)

## burn ##
@external
def burn(id: uint256, amount: uint256):
    # @dev burn one or more token with a certain ID
    # @dev the amount of tokens will be deducted from the holder's balance
    # @param receiver the account that will receive the minted token
    # @param id the ID of the token to burn
    # @param amount of tokens to burnfor this ID
    assert not self.paused, "The contract has been paused"
    assert self.balances[id][msg.sender] > 0 , "caller does not own this ID"
    operator: address = msg.sender
    fromBalance: uint256 = self.balances[id][msg.sender]
    assert fromBalance >= amount, "ERC1155: burn amount exceeds balance"
    self.balances[id][msg.sender] = fromBalance - amount

    log TransferSingle(operator, msg.sender, ZERO_ADDRESS, id, amount)
    
@external
def burnBatch(ids: DynArray[uint256, BATCH_SIZE], amounts: DynArray[uint256, BATCH_SIZE]):
    # @dev burn a batch of tokens with the passed IDs
    # @dev this can be burning non fungible tokens or reducing the balance of existing non-fungible token IDs in the contract
    # @dev inside the loop ownership will be checked for each token. We can not burn tokens we do not own
    # @param ids array of ids for the tokens to burn
    # @param amounts array of amounts of tokens for each ID in the ids array
    assert not self.paused, "The contract has been paused"
    assert len(ids) == len(amounts), "ERC1155: ids and amounts length mismatch"
    operator: address = msg.sender 
    
    for i in range(BATCH_SIZE):
        if i >= len(ids):
            break
        assert self.balances[ids[i]][msg.sender] > 0 , "Caller does not own this ID or ZERO balance"
        id: uint256 = ids[i]
        amount: uint256 = amounts[i]
        fromBalance: uint256 = self.balances[id][msg.sender]
        assert fromBalance >= amount, "ERC1155: burn amount exceeds balance"
        self.balances[id][msg.sender] = fromBalance - amount
    
    log TransferBatch(operator, msg.sender, ZERO_ADDRESS, ids, amounts)

## approval ##
@external
def setApprovalForAll(owner: address, operator: address, approved: bool):
    # @dev set an operator for a certain NFT owner address
    # @param account the NFT owner address
    # @param operator the operator address
    assert owner == msg.sender, "You can only set operators for your own account"
    assert not self.paused, "The contract has been paused"
    assert owner != operator, "ERC1155: setting approval status for self"
    self.operatorApprovals[owner][operator] = approved
    log ApprovalForAll(owner, operator, approved)

@external 
def isApprovedForAll(account: address, operator: address) -> bool:
    # @dev check wether operator is approved as an operator for the account
    # @param account the NFT owner address
    # @param operator the operator address
    assert self.paused == False, "The contract has been paused"
    return self.operatorApprovals[account][operator]

@external
def safeTransferFrom(sender: address, receiver: address, id: uint256, amount: uint256, bytes: bytes32):
    # @dev transfer token from one address to another.
    # @param sender the sending account (current owner)
    # @param receiver the receiving account
    # @param id the token id that will be sent
    # @param amount the amount of tokens for the specified id
    assert not self.paused, "The contract has been paused"
    assert receiver != ZERO_ADDRESS, "ERC1155: transfer to the zero address"
    assert receiver != sender, "ERC1155: transfer to self"
    assert (sender == msg.sender) or (self.operatorApprovals[sender][msg.sender] == True), "Caller is neither owner nor approved operator for this ID"
    assert self.balances[id][sender] > 0 , "caller does not own this ID or ZERO balance"
    operator: address = msg.sender
    fromBalance: uint256 = self.balances[id][sender]
    assert fromBalance >= amount, "ERC1155: insufficient balance for transfer"
    self.balances[id][sender] = fromBalance - amount
    self.balances[id][receiver] += amount
    log TransferSingle(operator, sender, receiver, id, amount)

@external
def safeBatchTransferFrom(sender: address, receiver: address, ids: DynArray[uint256, BATCH_SIZE], amounts: DynArray[uint256, BATCH_SIZE], _bytes: bytes32):
    # @dev transfer tokens from one address to another.
    # @param sender the sending account
    # @param receiver the receiving account
    # @param ids a dynamic array of the token ids that will be sent
    # @param amounts a dynamic array of the amounts for the specified list of ids.
    assert not self.paused, "The contract has been paused"
    assert receiver != ZERO_ADDRESS, "ERC1155: transfer to the zero address"
    assert (sender == msg.sender) or (self.operatorApprovals[sender][msg.sender] == True), "Caller is neither owner nor approved operator for this ID"
    assert len(ids) == len(amounts), "ERC1155: ids and amounts length mismatch"
    assert sender != receiver, "sending to self"
    operator: address = msg.sender
    for i in range(BATCH_SIZE):
        if i >= len(ids):
            break
        assert self.balances[ids[i]][sender] > 0 , "caller does not own this ID or ZERO balance"
        id: uint256 = ids[i]
        amount: uint256 = amounts[i]
        fromBalance: uint256 = self.balances[id][sender]
        assert fromBalance >= amount, "ERC1155: transfer amount exceeds balance"
        # self.balances[id][msg.sender] = fromBalance - amount
        self.balances[id][sender] = fromBalance - amount
        self.balances[id][receiver] += amount
    
    log TransferBatch(operator, sender, receiver, ids, amounts)

# misc #
@external
def setURI(uri: String[MAX_URI_LENGTH]):
    # @dev set the URI for the contract
    # @param uri the new uri for the contract
    assert not self.paused, "The contract has been paused"
    assert self.uri != uri, "new and current URI are identical"
    self.uri = uri

@external
def supportsInterface(interfaceId: bytes4) -> bool:
    return interfaceId in [
        ERC165_INTERFACE_ID,
        ERC1155_INTERFACE_ID,
        ERC1155_INTERFACE_ID_METADATA, 
    ] 

# @dev Implementation of ERC-721 non-fungible token standard.
# @author Jon Mardlin (@maurelian)
# @author Bryant Eisenbach (@fubuloubu, editor)

# Interface for the contract called by safeTransferFrom()
contract NFTReceiver:
    def onERC721Received(
            _operator: address,
            _from: address,
            _tokenId: uint256,
            _data: bytes[1024]
        ) -> bytes32: constant


# @dev Emits when ownership of any NFT changes by any mechanism. This event emits when NFTs are
#      created (`from` == 0) and destroyed (`to` == 0). Exception: during contract creation, any
#      number of NFTs may be created and assigned without emitting Transfer. At the time of any
#      transfer, the approved address for that NFT (if any) is reset to none.
# @param _from Sender of NFT (if address is zero address it indicates token creation).
# @param _to Receiver of NFT (if address is zero address it indicates token destruction).
# @param _tokenId The NFT that got transfered.
Transfer: event({
        _from: indexed(address),
        _to: indexed(address),
        _tokenId:indexed(uint256)
    })

# @dev This emits when the approved address for an NFT is changed or reaffirmed. The zero
#      address indicates there is no approved address. When a Transfer event emits, this also
#      indicates that the approved address for that NFT (if any) is reset to none.
# @param _owner Owner of NFT.
# @param _approved Address that we are approving.
# @param _tokenId NFT which we are approving.
Approval: event({
        _owner: indexed(address),
        _approved: indexed(address),
        _tokenId:indexed(uint256)
    })

# @dev This emits when an operator is enabled or disabled for an owner. The operator can manage
#      all NFTs of the owner.
# @param _owner Owner of NFT.
# @param _operator Address to which we are setting operator rights.
# @param _approved Status of operator rights(true if operator rights are given and false if
# revoked).
ApprovalForAll: event({
        _owner: indexed(address),
        _operator: indexed(address),
        _approved: bool
    })


# @dev Mapping from NFT ID to the address that owns it.
idToOwner: address[uint256]

# @dev Mapping from NFT ID to approved address.
idToApprovals: address[uint256]

# @dev Mapping from owner address to count of his tokens.
ownerToNFTokenCount: uint256[address]

# @dev Mapping from owner address to mapping of operator addresses.
ownerToOperators: (bool[address])[address]


# @dev Contract constructor. Per the Transfer event spec; during contract creation, any number of
#      NFTs may be created and assigned without emitting Transfer.
@public
def __init__(_recipients: address[64], _tokenIds: uint256[64]):
    for i in range(64):
        self.idToOwner[_tokenIds[i]] = _recipients[i]
        self.ownerToNFTokenCount[_recipients[i]] += 1


# @dev Returns the number of NFTs owned by `_owner`. NFTs assigned to the zero address are
#      considered invalid, and this function throws for queries about the zero address.
# @param _owner Address for whom to query the balance.
@public
@constant
def balanceOf(_owner: address) -> uint256:
    assert _owner != ZERO_ADDRESS
    return self.ownerToNFTokenCount[_owner]


# @dev Returns the address of the owner of the NFT. NFTs assigned to zero address are considered
#      invalid, and queries about them do throw.
# @param _tokenId The identifier for an NFT.
@public
@constant
def ownerOf(_tokenId: uint256) -> address:
    assert self.idToOwner[_tokenId] != ZERO_ADDRESS
    return self.idToOwner[_tokenId]


### TRANSFER FUNCTION HELPERS ###

# NOTE: as VYPER uses a new message call for a function call, I needed to pass `_sender: address`
#       rather than use msg.sender
# @dev Throws unless `msg.sender` is the current owner, an authorized operator, or the approved
#      address for this NFT.
# Throws if `_from` is not the current owner.
# Throws if `_to` is the zero address.
# Throws if `_tokenId` is not a valid NFT.
@private
def _validateTransferFrom(_from: address, _to: address, _tokenId: uint256, _sender: address):
    # Check that _to and _from are valid addresses
    assert _from != ZERO_ADDRESS
    assert _to != ZERO_ADDRESS
    # Throws if `_from` is not the current owner
    assert self.idToOwner[_tokenId] == _from
    # Throws unless `msg.sender` is the current owner, an authorized operator, or the approved
    # address for this NFT.
    senderIsOwner: bool = self.idToOwner[_tokenId] == _sender
    senderIsApproved: bool = self.idToApprovals[_tokenId] == _sender
    senderIsOperator: bool = (self.ownerToOperators[_from])[_sender]
    assert (senderIsOwner or senderIsApproved) or senderIsOperator


@private
def _doTransfer(_from: address, _to: address, _tokenId: uint256):
    # Change the owner
    self.idToOwner[_tokenId] = _to
    # Reset approvals
    self.idToApprovals[_tokenId] = ZERO_ADDRESS
    # Change count tracking
    self.ownerToNFTokenCount[_to] += 1
    self.ownerToNFTokenCount[_from] -= 1
    # Log the transfer
    log.Transfer(_from, _to, _tokenId)


### TRANSFER FUNCTIONS ###

# @dev Throws unless `msg.sender` is the current owner, an authorized operator, or the approved
#      address for this NFT.
#      Throws if `_from` is not the current owner.
#      Throws if `_to` is the zero address.
#      Throws if `_tokenId` is not a valid NFT.
# @notice The caller is responsible to confirm that `_to` is capable of receiving NFTs or else
#         they maybe be permanently lost.
# @param _from The current owner of the NFT.
# @param _to The new owner.
# @param _tokenId The NFT to transfer.
@public
def transferFrom(_from: address, _to: address, _tokenId: uint256):
    self._validateTransferFrom(_from, _to, _tokenId, msg.sender)
    self._doTransfer(_from, _to, _tokenId)


# @dev Transfers the ownership of an NFT from one address to another address.
# @notice Throws unless `msg.sender` is the current owner, an authorized operator, or the
#         approved address for this NFT. Throws if `_from` is not the current owner. Throws if `_to` is
#         the zero address. Throws if `_tokenId` is not a valid NFT. When transfer is complete, this
#         function checks if `_to` is a smart contract (code size > 0). If so, it calls `onERC721Received`
#         on `_to` and throws if the return value is not `bytes4(keccak256("onERC721Received(address,uint256,bytes)"))`.
#         NOTE: bytes4 is represented by bytes32 with padding
# @param _from The current owner of the NFT.
# @param _to The new owner.
# @param _tokenId The NFT to transfer.
# @param _data Additional data with no specified format, sent in call to `_to`.
@public
def safeTransferFrom(
        _from: address,
        _to: address,
        _tokenId: uint256,
        _data: bytes[1024]=""
    ):
    self._validateTransferFrom(_from, _to, _tokenId, msg.sender)
    self._doTransfer(_from, _to, _tokenId)
    _operator: address = ZERO_ADDRESS
    if(_to.codesize > 0):
        returnValue: bytes32 = NFTReceiver(_to).onERC721Received(_operator, _from, _tokenId, _data)
        assert returnValue == method_id("onERC721Received(address,address,uint256,bytes)", bytes32)


# @dev Set or reaffirm the approved address for an NFT.
# @notice The zero address indicates there is no approved address. Throws unless `msg.sender` is
#         the current NFT owner, or an authorized operator of the current owner.
# @param _approved Address to be approved for the given NFT ID.
# @param _tokenId ID of the token to be approved.
@public
def approve(_approved: address, _tokenId: uint256):
    # get owner
    owner: address = self.idToApprovals[_tokenId]
    # check requirements
    senderIsOwner: bool = self.idToOwner[_tokenId] == msg.sender
    senderIsOperator: bool = (self.ownerToOperators[owner])[msg.sender]
    assert (senderIsOwner or senderIsOperator)
    # set the approval
    self.idToApprovals[_tokenId] = _approved
    log.Approval(owner, _approved, _tokenId)


# @dev Enables or disables approval for a third party ("operator") to manage all of
#      `msg.sender`'s assets. It also emits the ApprovalForAll event.
# @notice This works even if sender doesn't own any tokens at the time.
# @param _operator Address to add to the set of authorized operators.
# @param _approved True if the operators is approved, false to revoke approval.
@public
def setApprovalForAll(_operator: address, _approved: bool):
    assert _operator != ZERO_ADDRESS
    self.ownerToOperators[msg.sender][_operator] = _approved
    log.ApprovalForAll(msg.sender, _operator, _approved)


# @dev Get the approved address for a single NFT.
# @notice Throws if `_tokenId` is not a valid NFT.
# @param _tokenId ID of the NFT to query the approval of.
@public
@constant
def getApproved(_tokenId: uint256) -> address:
    assert self.idToOwner[_tokenId] != ZERO_ADDRESS
    return self.idToApprovals[_tokenId]


# @dev Checks if `_operator` is an approved operator for `_owner`.
# @param _owner The address that owns the NFTs.
# @param _operator The address that acts on behalf of the owner.
@public
@constant
def isApprovedForAll( _owner: address, _operator: address) -> bool:
    # TODO: check original for _owner == 0x0
    if (_owner == ZERO_ADDRESS):
        return False
    return (self.ownerToOperators[_owner])[_operator]

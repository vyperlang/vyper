# @version 0.3.1
# Author: Sören Steiger, github.com/ssteiger
# Edit: sonnhfit
# License: MIT

# ERC1155 Token Standard
# https://eips.ethereum.org/EIPS/eip-1155


interface ERC1155TokenReceiver:
    def onERC1155Received(
        _operator: address,
        _from: address,
        _id: uint256,
        _value: uint256,
        _data: Bytes[256]
    ) -> bytes32: view # TODO: should return bytes4
    def onERC1155BatchReceived(
        _operator: address,
        _from: address,
        _ids: uint256[BATCH_SIZE],
        _values: uint256[BATCH_SIZE],
        _data: Bytes[256]
    ) -> bytes32: view # TODO: should return bytes4


# @dev Either `TransferSingle` or `TransferBatch` MUST emit when tokens are transferred, including zero value transfers as well as minting or burning (see "Safe Transfer Rules" section of the standard).
#      The `_operator` argument MUST be the address of an account/contract that is approved to make the transfer (SHOULD be msg.sender).
#      The `_from` argument MUST be the address of the holder whose balance is decreased.
#      The `_to` argument MUST be the address of the recipient whose balance is increased.
#      The `_id` argument MUST be the token type being transferred.
#      The `_value` argument MUST be the number of tokens the holder balance is decreased by and match what the recipient balance is increased by.
#      When minting/creating tokens, the `_from` argument MUST be set to `0x0` (i.e. zero address).
#      When burning/destroying tokens, the `_to` argument MUST be set to `0x0` (i.e. zero address).
# event TransferSingle(address indexed _operator, address indexed _from, address indexed _to, uint256 _id, uint256 _value);

event TransferSingle:
    _operator: indexed(address)
    _from: indexed(address)
    _to: indexed(address)
    _id: uint256
    _value: uint256

# @dev Either `TransferSingle` or `TransferBatch` MUST emit when tokens are transferred, including zero value transfers as well as minting or burning (see "Safe Transfer Rules" section of the standard).
#      The `_operator` argument MUST be the address of an account/contract that is approved to make the transfer (SHOULD be msg.sender).
#      The `_from` argument MUST be the address of the holder whose balance is decreased.
#      The `_to` argument MUST be the address of the recipient whose balance is increased.
#      The `_ids` argument MUST be the list of tokens being transferred.
#      The `_values` argument MUST be the list of number of tokens (matching the list and order of tokens specified in _ids) the holder balance is decreased by and match what the recipient balance is increased by.
#      When minting/creating tokens, the `_from` argument MUST be set to `0x0` (i.e. zero address).
#      When burning/destroying tokens, the `_to` argument MUST be set to `0x0` (i.e. zero address).
# event TransferBatch(address indexed _operator, address indexed _from, address indexed _to, uint256[] _ids, uint256[] _values);

event TransferBatch:
    _operator: indexed(address)
    _from: indexed(address)
    _to: indexed(address)
    _ids: uint256[BATCH_SIZE]
    _value: uint256[BATCH_SIZE]


# @dev MUST emit when approval for a second party/operator address to manage all tokens for an owner address is enabled or disabled (absence of an event assumes disabled).
# event ApprovalForAll(address indexed _owner, address indexed _operator, bool _approved);
event ApprovalForAll:
    _owner: indexed(address)
    _operator: indexed(address)
    _approved: bool



supportedInterfaces: HashMap[bytes32, bool]

# https://eips.ethereum.org/EIPS/eip-165
ERC165_INTERFACE_ID: constant(bytes32)  = 0x0000000000000000000000000000000000000000000000000000000001ffc9a7
ERC1155_INTERFACE_ID: constant(bytes32) = 0x00000000000000000000000000000000000000000000000000000000d9b67a26

tokensIdCount: uint256

_balanceOf: HashMap[address, HashMap[uint256, uint256]]
operators: HashMap[address, HashMap[address, bool]]


# TODO: decide which batch size to use
BATCH_SIZE: constant(uint256) = 5


@external
def __init__():
    self.tokensIdCount = 0
    self.supportedInterfaces[ERC165_INTERFACE_ID] = True
    self.supportedInterfaces[ERC1155_INTERFACE_ID] = True


@external
@view
def supportsInterface(_interfaceID: bytes32) -> bool:
    return self.supportedInterfaces[_interfaceID]


# @notice Transfers `_value` amount of an `_id` from the `_from` address to the `_to` address specified (with safety call).
# @dev Caller must be approved to manage the tokens being transferred out of the `_from` account (see "Approval" section of the standard).
#      MUST revert if `_to` is the zero address.
#      MUST revert if balance of holder for token `_id` is lower than the `_value` sent.
#      MUST revert on any other error.
#      MUST emit the `TransferSingle` event to reflect the balance change (see "Safe Transfer Rules" section of the standard).
#      After the above conditions are met, this function MUST check if `_to` is a smart contract (e.g. code size > 0). If so, it MUST call `onERC1155Received` on `_to` and act appropriately (see "Safe Transfer Rules" section of the standard).
# @param _from    Source address
# @param _to      Target address
# @param _id      ID of the token type
# @param _value   Transfer amount
# @param _data    Additional data with no specified format, MUST be sent unaltered in call to `onERC1155Received` on `_to`
# function safeTransferFrom(address _from, address _to, uint256 _id, uint256 _value, bytes calldata _data) external;
@external
def safeTransferFrom(
    _from: address,
    _to: address,
    _id: uint256,
    _value: uint256,
    _data: Bytes[256]
  ):
    assert _from == msg.sender or (self.operators[_from])[msg.sender]
    assert _to != ZERO_ADDRESS
    assert self._balanceOf[_from][_id] >= _value

    if _to.is_contract:
        returnValue: bytes32 = ERC1155TokenReceiver(_to).onERC1155Received(msg.sender, _from, _id, _value, _data)
        assert returnValue == method_id("onERC1155Received(address,address,uint256,uint256,bytes)", output_type=bytes32)

    self._balanceOf[_from][_id] -= _value
    self._balanceOf[_to][_id] += _value
    log TransferSingle(msg.sender, _from, _to, _id, _value)


# @notice Transfers `_values` amount(s) of `_ids` from the `_from` address to the `_to` address specified (with safety call).
# @dev Caller must be approved to manage the tokens being transferred out of the `_from` account (see "Approval" section of the standard).
#      MUST revert if `_to` is the zero address.
#      MUST revert if length of `_ids` is not the same as length of `_values`.
#      MUST revert if any of the balance(s) of the holder(s) for token(s) in `_ids` is lower than the respective amount(s) in `_values` sent to the recipient.
#      MUST revert on any other error.
#      MUST emit `TransferSingle` or `TransferBatch` event(s) such that all the balance changes are reflected (see "Safe Transfer Rules" section of the standard).
#      Balance changes and events MUST follow the ordering of the arrays (_ids[0]/_values[0] before _ids[1]/_values[1], etc).
#      After the above conditions for the transfer(s) in the batch are met, this function MUST check if `_to` is a smart contract (e.g. code size > 0). If so, it MUST call the relevant `ERC1155TokenReceiver` hook(s) on `_to` and act appropriately (see "Safe Transfer Rules" section of the standard).
# @param _from    Source address
# @param _to      Target address
# @param _ids     IDs of each token type (order and length must match _values array)
# @param _values  Transfer amounts per token type (order and length must match _ids array)
# @param _data    Additional data with no specified format, MUST be sent unaltered in call to the `ERC1155TokenReceiver` hook(s) on `_to`
# function safeBatchTransferFrom(address _from, address _to, uint256[] calldata _ids, uint256[] calldata _values, bytes calldata _data) external;
@external
def safeBatchTransferFrom(
    _from: address,
    _to: address,
    _ids: uint256[BATCH_SIZE],
    _values: uint256[BATCH_SIZE],
    _data: Bytes[256]
  ):
    assert _from == msg.sender or (self.operators[_from])[msg.sender]
    assert _to != ZERO_ADDRESS
    #assert len(_ids) == len(_values)

    for i in range(BATCH_SIZE):
        assert self._balanceOf[_from][_ids[i]] >= _values[i]
        self._balanceOf[_from][_ids[i]] -= _values[i]
        self._balanceOf[_to][_ids[i]] += _values[i]
        if _to.is_contract:
            returnValue: bytes32 = ERC1155TokenReceiver(_to).onERC1155Received(msg.sender, _from, _ids[i], _values[i], _data)
            assert returnValue == method_id("onERC1155Received(address,address,uint256,uint256,bytes)", output_type=bytes32)

    log TransferBatch(msg.sender, _from, _to, _ids, _values)


# @notice Get the balance of an account's tokens.
# @param  _owner The address of the token holder
# @param  _id ID of the token
# @return The _owner's balance of the token type requested
# function balanceOf(address _owner, uint256 _id) external view returns (uint256);
@external
@view
def balanceOf(
    _owner: address,
    _id: uint256
  ) -> uint256:
    assert _owner != ZERO_ADDRESS
    return self._balanceOf[_owner][_id]


# @notice Get the balance of multiple account/token pairs
# @param _owners The addresses of the token holders
# @param _ids    ID of the tokens
# @return        The _owner's balance of the token types requested (i.e. balance for each (owner, id) pair)
# function balanceOfBatch(address[] calldata _owners, uint256[] calldata _ids) external view returns (uint256[] memory);
@external
@view
def balanceOfBatch(
    _owner: address[BATCH_SIZE],
    _ids: uint256[BATCH_SIZE]
  ) -> uint256[BATCH_SIZE]:
    returnValues: uint256[BATCH_SIZE] = empty(uint256[BATCH_SIZE])
    for i in range(BATCH_SIZE):
        returnValues[i] = self._balanceOf[_owner[i]][_ids[i]]
    return returnValues


# @notice Enable or disable approval for a third party ("operator") to manage all of the caller's tokens.
# @dev MUST emit the ApprovalForAll event on success.
# @param _operator  Address to add to the set of authorized operators
# @param _approved  True if the operator is approved, false to revoke approval
# function setApprovalForAll(address _operator, bool _approved) external;
@external
def setApprovalForAll(
    _operator: address,
    _approved: bool
  ):
    (self.operators[msg.sender])[_operator] = _approved
    log ApprovalForAll(msg.sender, _operator, _approved)


# @notice Queries the approval status of an operator for a given owner.
# @param _owner     The owner of the tokens
# @param _operator  Address of authorized operator
# @return           True if the operator is approved, false if not
# function isApprovedForAll(address _owner, address _operator) external view returns (bool);
@external
@view
def isApprovedForAll(
    _owner: address,
    _operator: address
  ) -> bool:
    return (self.operators[_owner])[_operator]


# NOTE: This is not part of the standard
# TODO: Right now anyone can mint
@external
def mint(
    _to: address,
    _supply: uint256,
    _data: Bytes[256]
  ) -> uint256:
    assert _to != ZERO_ADDRESS
    self._balanceOf[msg.sender][self.tokensIdCount] = _supply
    self.tokensIdCount += 1
    log TransferSingle(msg.sender, ZERO_ADDRESS, _to, self.tokensIdCount, _supply)
    return self.tokensIdCount


# NOTE: This is not part of the standard
# TODO: Right now anyone can mint
@external
def mintBatch(
    _to: address,
    _supplys: uint256[BATCH_SIZE],
    _data: Bytes[256]
  ) -> uint256[BATCH_SIZE]:
    assert _to != ZERO_ADDRESS
    ids: uint256[BATCH_SIZE] = empty(uint256[BATCH_SIZE])
    for i in range(BATCH_SIZE):
        self._balanceOf[msg.sender][self.tokensIdCount] = _supplys[i]
        self.tokensIdCount += 1
        id: uint256 = self.tokensIdCount
        ids[i] = id

    log TransferBatch(msg.sender, ZERO_ADDRESS, _to, ids, _supplys)
    return ids


# TODO: specify a burn()/burnBatch() 

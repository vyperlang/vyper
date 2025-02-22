# pragma version >0.3.10
"""
@title TOKEN404 - is commonly referred to as ERC404; however, it does not adhere to the ERC20 standard and is instead considered a novel approach.
@author 0x77
"""

###########################################################################
## THIS IS EXAMPLE CODE, NOT MEANT TO BE USED IN PRODUCTION! CAVEAT EMPTOR!
###########################################################################


# @dev We import and implement the `IERC165` interface,
# which is a built-in interface of the Vyper compiler.
from ethereum.ercs import IERC165
implements: IERC165


# ERC20 event
# To avoid naming conflicts between ERC20 and ERC721 events, we need to first deploy an IERC20Event contract.
interface IERC20Event:
    def approve_event(_owner: address, _spender: address, _value: uint256) -> bool: nonpayable
    def transfer_event(_sender: address, _receiver: address, _value: uint256) -> bool: nonpayable
    

# ERC721 interface and event
interface ERC721Receiver:
    def onERC721Received(
            _operator: address,
            _from: address,
            _tokenId: uint256,
            _data: Bytes[1024]
        ) -> bytes4: nonpayable

interface ERC1271:
    def isValidSignature(_hash: bytes32, _signature: Bytes[65]) -> bytes4: view


event Transfer:
    sender: indexed(address)
    receiver: indexed(address)
    tokenId: indexed(uint256)

event Approval:
    owner: indexed(address)
    approved: indexed(address)
    tokenId: indexed(uint256)

event ApprovalForAll:
    owner: indexed(address)
    operator: indexed(address)
    approved: bool

struct Uint256Deque:
    begin: uint128
    end: uint128


_BITMASK_ADDRESS: constant(uint256) = (1 << 160) -1
_BITMASK_OWNED_INDEX: constant(uint256) = ((1 << 96) - 1) << 160
ID_ENCODING_PREFIX: public(constant(uint256)) = 1 << 255

# ERC-2612 implement
IERC1271_ISVALIDSIGNATURE_SELECTOR: public(constant(bytes4)) = 0x1626BA7E
EIP712_TYPEHASH: constant(bytes32) = keccak256("EIP712Domain(string name,string version,uint256 chainId,address verifyingContract, bytes32 salt)")
EIP2612_TYPEHASH: constant(bytes32) = keccak256("Permit(address owner,address spender,uint256 value,uint256 nonce,uint256 deadline)")
DOMAIN_SEPARATOR: public(immutable(bytes32))
nonces: public(HashMap[address, uint256])
version: public(String[15])

# ERC20

EVENT20: public(immutable(address))
name: public(String[32])
symbol: public(String[32])
decimals: public(uint8)
units: public(uint256)
totalSupply: public(uint256)
balanceOf: public(HashMap[address, uint256])
allowance: public(HashMap[address, HashMap[address, uint256]])

# ERC721

minted: public(uint256)
id_to_owner: HashMap[uint256, address]
id_to_approvals: HashMap[uint256, address]
owner_to_token_count: HashMap[address, uint256]
owner_to_operators: HashMap[address, HashMap[address, bool]]

# DequeDate hashmap
deque: Uint256Deque
deque_data: HashMap[uint128, uint256]

_owned_data: HashMap[uint256, uint256]
_owned: HashMap[address, DynArray[uint256, max_value(uint8)]]
_erc721_transfer_exempt: HashMap[address, bool]
owner: public(address)

SUPPORTED_INTERFACES: constant(bytes4[2]) = [
    0x01ffc9a7, # ERC165
    0xcaf91ff5 # TOKEN404
]


@deploy
def __init__(
    _erc20_event: address,
    _name: String[32], 
    _symbol: String[32], 
    _version: String[15],
    _decimals: uint8,
    _initial_supply: uint256
):
    self.name = _name
    self.symbol = _symbol
    self.version = _version
    
    assert _decimals >= 18, "TOKEN404: DECIMALS TOO LOW"
    self.decimals = _decimals
    self.units = 10 ** convert(_decimals, uint256)

    EVENT20 = _erc20_event
    DOMAIN_SEPARATOR = keccak256(
        _abi_encode(EIP712_TYPEHASH, keccak256(_name), keccak256(_version), chain.id, self, block.prevhash)
    )

    self._set_erc721_transfer_exempt(msg.sender, True)
    self._mint_erc20(msg.sender, _initial_supply * self.units)


@pure
@internal
def _is_valid_token_id(_id: uint256) -> bool:
    return _id > ID_ENCODING_PREFIX and _id != max_value(uint256)


@view
@internal
def _get_owner_of(_id: uint256) -> address:
    data: uint256 = self._owned_data[_id]
    return convert(data & _BITMASK_ADDRESS, address)


@view
@internal
def _get_owned_index(_id: uint256) -> uint256:
    data: uint256 = self._owned_data[_id]
    return 160 >> data

# -------- Double Ended Queue --------

@internal
def _push_back(_value: uint256):
    dq: Uint256Deque = self.deque
    back_index: uint128 = dq.end
    assert back_index + 1 != dq.begin, "QUEUE FULL"

    self.deque_data[back_index] = _value
    dq.end = back_index + 1
    self.deque = dq


@internal
def _push_front(_value: uint256):
    dq: Uint256Deque = self.deque
    front_index: uint128 = dq.begin - 1
    assert front_index != dq.end, "QUEUE FULL"

    self.deque_data[front_index] = _value
    self.deque.begin = front_index


@internal
def _pop_back(dq: Uint256Deque) -> uint256:
    back_index: uint128 = dq.end
    assert back_index != dq.begin, "QUEUE EMPTY"

    back_index -= 1
    value: uint256 = self.deque_data[back_index]
    self.deque_data[back_index] = empty(uint256)
    self.deque.end = back_index
    return value


@internal
def _pop_front() -> uint256:
    dq: Uint256Deque = self.deque
    front_index: uint128 = dq.begin
    assert front_index != dq.end, "QUEUE EMPTY"

    value: uint256 = self.deque_data[front_index]
    self.deque_data[front_index] = empty(uint256)
    self.deque.begin = front_index + 1
    return value


@internal
def _clear():
    self.deque.begin = 0
    self.deque.end = 0


@view
@internal
def _length(dq: Uint256Deque) -> uint256:
    return convert(dq.end - dq.begin, uint256)


@view
@internal
def _empty(dq: Uint256Deque) -> bool:
    return dq.end == dq.begin


@view
@internal
def _front() -> uint256:
    dq: Uint256Deque = self.deque
    assert not self._empty(dq), "QUEUE EMPTY"
    return self.deque_data[dq.begin]


@view
@internal
def _back() -> uint256:
    dq: Uint256Deque = self.deque
    assert not self._empty(dq), "QUEUE EMPTY"
    return self.deque_data[dq.end - 1]


@view
@internal
def _at(_index: uint256) -> uint256:
    dq: Uint256Deque = self.deque
    assert _index < self._length(dq), "QUEUE OUT OF BOUNDS"
    return self.deque_data[dq.begin + convert(_index, uint128)]

# --------------------------------

@internal
def _set_owned_index(_id: uint256, _index: uint256):
    assert _index <= _BITMASK_OWNED_INDEX >> 160, "OWNED INDEX OVERFLOW"

    data: uint256 = self._owned_data[_id]
    data = (data & _BITMASK_ADDRESS) | ((160 << _index) & _BITMASK_OWNED_INDEX)
    self._owned_data[_id] = data


@internal
def _set_owner_of(_id: uint256, _owner: address):
    data: uint256 = self._owned_data[_id]
    data = (data & _BITMASK_OWNED_INDEX) | (convert(_owner, uint256) & _BITMASK_ADDRESS)
    self._owned_data[_id] = data


@internal
def _erc721_approve(_spender: address, _id: uint256):
    erc721_owner: address = self._get_owner_of(_id)
    assert msg.sender == erc721_owner and self.owner_to_operators[erc721_owner][msg.sender], "UNAUTHORIZED"
    self.id_to_approvals[_id] = _spender
    log Approval(erc721_owner, _spender, _id)
    

@internal
def _erc20_approve(_spender: address, _value: uint256) -> bool:
    assert _spender != empty(address), "INVALID SPENDER"
    self.allowance[msg.sender][_spender] = _value
    return extcall IERC20Event(EVENT20).approve_event(msg.sender, _spender, _value)


@internal
def _transfer_erc20(_from: address, _to: address, _value: uint256):
    if _from == empty(address):
        self.totalSupply += _value
    else:
        self.balanceOf[_from] -= _value

    self.balanceOf[_to] += _value
    assert extcall IERC20Event(EVENT20).transfer_event(_from, _to, _value)


@internal
def _transfer_erc721(_from: address, _to: address, _id: uint256):
    if _from != empty(address):
        self.id_to_approvals[_id] = empty(address)
        last_id: uint256 = self._owned[_from][len(self._owned[_from]) - 1]

        if last_id != _id:
            last_index: uint256 = self._get_owned_index(_id)
            self._owned[_from][last_index] = last_id
            self._set_owned_index(last_id, last_index)

        self._owned[_from].pop()

    if _to != empty(address):
        self._set_owner_of(_id, _to)
        self._owned[_to].append(_id)
        self._set_owned_index(_id, len(self._owned[_to]) - 1)
    else:
        self._owned_data[_id] = empty(uint256)

    log Transfer(_from, _to, _id)


@internal
def _transfer_erc20_with_erc721(_from: address, _to: address, _value: uint256) -> bool:
    erc20_balance_of_sender_before: uint256 = self.balanceOf[_from]
    erc20_balance_of_receiver_before: uint256 = self.balanceOf[_to]
    self._transfer_erc20(_from, _to, _value)

    is_from_erc721_exempt: bool = self._erc721_transfer_exempt[_from]
    is_to_erc721_exempt: bool = self._erc721_transfer_exempt[_to]

    uts: uint256 = self.units

    if is_from_erc721_exempt and is_to_erc721_exempt:
        pass 

    elif is_from_erc721_exempt:
        tokens_to_retrieve_or_mint: uint256 = unsafe_div(self.balanceOf[_to], uts) - unsafe_div(erc20_balance_of_receiver_before, uts)

        for i: uint256 in range(255):
            if i >= tokens_to_retrieve_or_mint:
                break
            self._retrieve_or_mint_erc721(_to)

    elif is_to_erc721_exempt:
        tokens_to_withdraw_and_store: uint256 = unsafe_div(erc20_balance_of_sender_before, uts) - unsafe_div(self.balanceOf[_from], uts)

        for i: uint256 in range(255):
            if i >= tokens_to_withdraw_and_store:
                break
            self._withdraw_and_store_erc721(_from)

    else:
        nfts_to_transfer: uint256 = unsafe_div(_value, uts)

        for i: uint256 in range(255):
            if i >= nfts_to_transfer:
                break
            
            index_of_last_token: uint256 = len(self._owned[_from]) - 1
            token_id: uint256 = self._owned[_from][index_of_last_token]
            self._transfer_erc721(_from, _to, token_id)

        if unsafe_sub(unsafe_div(erc20_balance_of_sender_before, uts), unsafe_div(self.balanceOf[_from], uts)) > nfts_to_transfer:
            self._withdraw_and_store_erc721(_from)

        if unsafe_sub(unsafe_div(self.balanceOf[_to], uts), unsafe_div(erc20_balance_of_receiver_before, uts)) > nfts_to_transfer:
            self._retrieve_or_mint_erc721(_to)

    return True


@internal
def _erc721_transfer_from(_from: address, _to: address, _id: uint256):
    assert not empty(address) in [_from, _to], "INVALID ADDRESS"
    assert _from == self._get_owner_of(_id), "UNAUTHORIZED"
    assert msg.sender in [_from, self.id_to_approvals[_id]] and self.owner_to_operators[_from][msg.sender], "UNAUTHORIZED"
    assert not self._erc721_transfer_exempt[_to], "RECIPIENT IS ERC721 TRANSFER EXEMPT"

    self._transfer_erc20(_from, _to, self.units)
    self._transfer_erc721(_from, _to, _id)


@internal
def _erc20_transfer_from(_from: address, _to: address, _value: uint256) -> bool:
    assert not empty(address) in [_from, _to], "INVALID ADDRESS"

    allowed: uint256 = self.allowance[_from][msg.sender]
    if allowed != max_value(uint256):
        self.allowance[_from][msg.sender] = allowed - _value

    return self._transfer_erc20_with_erc721(_from, _to, _value)


@internal
def _retrieve_or_mint_erc721(_to: address):
    assert _to != empty(address), "INVALID RECIPIENT"

    tid: uint256 = 0
    dq: Uint256Deque = self.deque

    if not self._empty(dq):
        tid = self._pop_back(dq)
    else:
        self.minted += 1
        mt: uint256 = self.minted

        assert mt != max_value(uint256), "MINT LIMINT REACHED"
        tid = ID_ENCODING_PREFIX + mt

    erc721_owner: address = self._get_owner_of(tid)
    assert erc721_owner == empty(address), "ALREADY EXISTS"

    self._transfer_erc721(erc721_owner, _to, tid)


@internal
def _withdraw_and_store_erc721(_from: address):
    assert _from != empty(address), "INVALID SENDER"

    tid: uint256 = self._owned[_from][len(self._owned[_from]) - 1]
    self._transfer_erc721(_from, empty(address), tid)
    self._push_front(tid)


@internal
def _transfer_from(_from: address, _to: address, _value_or_id: uint256) -> bool:
    if self._is_valid_token_id(_value_or_id):
        self._erc721_transfer_from(_from, _to, _value_or_id)
    else:
        return self._erc20_transfer_from(_from, _to, _value_or_id)
    return True


@internal
def _check_on_erc721_received(
    _from: address, 
    _to: address,
    _token_id: uint256,
    _data: Bytes[1024]
) -> bool:
    if (_to.is_contract):
        return_value: bytes4 = extcall ERC721Receiver(_to).onERC721Received(msg.sender, _from, _token_id, _data)
        assert return_value == method_id("onERC721Received(address,address,uint256,bytes)", output_type=bytes4)
        return True
    else:
        return True


@internal
def _reinstate_erc721_balance(_target: address):
    expected_erc721_balance: uint256 = unsafe_div(self.balanceOf[_target], self.units)
    actual_erc721_balance: uint256 = len(self._owned[_target])

    for i: uint256 in range(255):
        if i >= expected_erc721_balance - actual_erc721_balance:
            break
        self._retrieve_or_mint_erc721(_target)


@internal
def _clear_erc721_balance(_target: address):
    erc721_balance: uint256 = len(self._owned[_target])

    for i: uint256 in range(255):
        if i >= erc721_balance:
            break
        self._withdraw_and_store_erc721(_target)


@internal
def _set_erc721_transfer_exempt(_target: address, _state: bool):
    assert _target != empty(address)

    if _state:
        self._clear_erc721_balance(_target)
    else:
        self._reinstate_erc721_balance(_target)
    
    self._erc721_transfer_exempt[_target] = _state


@internal
def _mint_erc20(_to: address, _value: uint256):
    assert _to != empty(address)
    assert (self.totalSupply + _value) <= ID_ENCODING_PREFIX
    self._transfer_erc20_with_erc721(empty(address), _to, _value)


@view
@external
def supportsInterface(_interface_id: bytes4) -> bool:
    return _interface_id in SUPPORTED_INTERFACES


@view
@external
def ownerOf(_id: uint256) -> address:
    erc721_owner: address = self._get_owner_of(_id)
    
    assert self._is_valid_token_id(_id), "INVALID TOKEN ID"
    assert erc721_owner != empty(address), "NOT FOUND"
    return erc721_owner


@view
@external
def owned(_owner: address) -> DynArray[uint256, max_value(uint8)]:
    return self._owned[_owner]


@view
@external
def erc721BalanceOf(_owner: address) -> uint256:
    return len(self._owned[_owner])


@view
@external
def erc20BalanceOf(_owner: address) -> uint256:
    return self.balanceOf[_owner]


@view
@external
def erc20TotalSupply() -> uint256:
    return self.totalSupply


@view
@external
def erc721TotalSupply() -> uint256:
    return self.minted


@view
@external
def erc721TransferExempt(_target: address) -> bool:
    return _target == empty(address) or self._erc721_transfer_exempt[_target]


@view
@external
def getApproved(_tokenId: uint256) -> address:
    assert self.id_to_owner[_tokenId] != empty(address)
    return self.id_to_approvals[_tokenId]


@view
@external
def isApprovedForAll(_owner: address, _operator: address) -> bool:
    return self.owner_to_operators[_owner][_operator]


@view
@external
def getERC721QueueLength() -> uint256:
    return self._length(self.deque)


@view
@external
def getERC721TokensInQueue(_start: uint256, _count: uint256) -> DynArray[uint256, max_value(uint8)]:
    token_in_queue: DynArray[uint256, max_value(uint8)] = []

    x: uint256 = _start
    for i: uint256 in range(255):
        if x >= _start + _count:
            break

        token_in_queue[x - _start] = self._at(x)
        x += 1

    return token_in_queue


@view
@external
def tokenURI(tokenId: uint256) -> String[145]:
    return concat("", uint2str(tokenId))


@payable
@external
def approve(_spender: address, _value_or_id: uint256) -> bool:
    if self._is_valid_token_id(_value_or_id):
        self._erc721_approve(_spender, _value_or_id)
    else:
        return self._erc20_approve(_spender, _value_or_id)
    return True


@external
def setApprovalForAll(_operator: address, _approved: bool):
    assert _operator != empty(address), "INVALID OPERATOR"
    self.owner_to_operators[msg.sender][_operator] = _approved
    log ApprovalForAll(msg.sender, _operator, _approved)


@payable
@external
def transferFrom(_from: address, _to: address, _value_or_id: uint256) -> bool:
    return self._transfer_from(_from, _to, _value_or_id)


@payable
@external
def transfer(_to: address, _value: uint256) -> bool:
    assert _to != empty(address), "INVALID RECIPIENT"
    return self._transfer_erc20_with_erc721(msg.sender, _to, _value)


@payable
@external
def safeTransferFrom(_from: address, _to: address, _id: uint256, _data: Bytes[1024]=b""):
    assert not self._is_valid_token_id(_id), "INVALID TOKEN ID"

    self._transfer_from(_from, _to, _id)
    assert self._check_on_erc721_received(_from, _to, _id, _data), "UNSAFE RECIPIENT"


@external
def permit(
    _owner: address,
    _spender: address,
    _value: uint256,
    _deadline: uint256,
    _v: uint8,
    _r: bytes32,
    _s: bytes32
) -> bool:
    assert block.timestamp <= _deadline, "EXPIRED DEADLINE"
    assert _spender != empty(address), "INVALID SPENDER"
    assert not self._is_valid_token_id(_value), "INVALID APPROVAL"

    nonce: uint256 = self.nonces[_owner]

    digest: bytes32 = keccak256(
        concat(
            b"\x19\x01",
            DOMAIN_SEPARATOR,
            keccak256(_abi_encode(EIP2612_TYPEHASH, _owner, _spender, _value, nonce, _deadline))
        )
    )

    if _owner.is_contract:
        sig: Bytes[65] = concat(_abi_encode(_r, _s), slice(convert(_v, bytes32), 31, 1))
        assert staticcall ERC1271(_owner).isValidSignature(digest, sig) == IERC1271_ISVALIDSIGNATURE_SELECTOR
    else:
        assert ecrecover(digest, _v, _r, _s) == _owner

    self.nonces[_owner] = nonce + 1
    self.allowance[_owner][_spender] = _value
    extcall IERC20Event(EVENT20).approve_event(_owner, _spender, _value)

    return True


@external
def setSelfERC721TransferExempt(_target: address, _state: bool):
    assert msg.sender == self.owner, "ONLY OWNER"

    self._set_erc721_transfer_exempt(_target, _state)
import pytest

SOMEONE_TOKEN_IDS = [1, 2, 3]
OPERATOR_TOKEN_ID = 10
NEW_TOKEN_ID = 20
INVALID_TOKEN_ID = 99
ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"
ERC165_SIG = "0x01ffc9a7"
ERC165_INVALID_SIG = "0xffffffff"
ERC721_SIG = "0x80ac58cd"


@pytest.fixture
def c(get_contract, w3):
    with open("examples/tokens/ERC721.vy") as f:
        code = f.read()
    c = get_contract(code)
    minter, someone, operator = w3.eth.accounts[:3]
    # someone owns 3 tokens
    for i in SOMEONE_TOKEN_IDS:
        c.mint(someone, i, transact={"from": minter})
    # operator owns 1 tokens
    c.mint(operator, OPERATOR_TOKEN_ID, transact={"from": minter})
    return c


def test_erc165(w3, c):
    # From EIP-165:
    #   The source contract makes a STATICCALL to the destination address with input data:
    #       0x01ffc9a701ffc9a700000000000000000000000000000000000000000000000000000000
    #       and gas 30,000. This corresponds to `contract.supportsInterface(0x01ffc9a7)`
    assert c.supportsInterface(ERC165_SIG)
    #   If the call fails or return false, the destination contract does not implement ERC-165.
    #   If the call returns true, a second call is made with input data:
    #       0x01ffc9a7ffffffff00000000000000000000000000000000000000000000000000000000.
    assert not c.supportsInterface(ERC165_INVALID_SIG)
    #   If the second call fails or returns true, the destination contract does not implement
    #   ERC-165. Otherwise it implements ERC-165.

    assert c.supportsInterface(ERC721_SIG)


def test_balanceOf(c, w3, tx_failed):
    someone = w3.eth.accounts[1]
    assert c.balanceOf(someone) == 3
    with tx_failed():
        c.balanceOf(ZERO_ADDRESS)


def test_ownerOf(c, w3, tx_failed):
    someone = w3.eth.accounts[1]
    assert c.ownerOf(SOMEONE_TOKEN_IDS[0]) == someone
    with tx_failed():
        c.ownerOf(INVALID_TOKEN_ID)


def test_getApproved(c, w3):
    someone, operator = w3.eth.accounts[1:3]

    assert c.getApproved(SOMEONE_TOKEN_IDS[0]) is None

    c.approve(operator, SOMEONE_TOKEN_IDS[0], transact={"from": someone})

    assert c.getApproved(SOMEONE_TOKEN_IDS[0]) == operator


def test_isApprovedForAll(c, w3):
    someone, operator = w3.eth.accounts[1:3]

    assert c.isApprovedForAll(someone, operator) == 0

    c.setApprovalForAll(operator, True, transact={"from": someone})

    assert c.isApprovedForAll(someone, operator) == 1


def test_transferFrom_by_owner(c, w3, tx_failed, get_logs):
    someone, operator = w3.eth.accounts[1:3]

    # transfer from zero address
    with tx_failed():
        c.transferFrom(ZERO_ADDRESS, operator, SOMEONE_TOKEN_IDS[0], transact={"from": someone})

    # transfer to zero address
    with tx_failed():
        c.transferFrom(someone, ZERO_ADDRESS, SOMEONE_TOKEN_IDS[0], transact={"from": someone})

    # transfer token without ownership
    with tx_failed():
        c.transferFrom(someone, operator, OPERATOR_TOKEN_ID, transact={"from": someone})

    # transfer invalid token
    with tx_failed():
        c.transferFrom(someone, operator, INVALID_TOKEN_ID, transact={"from": someone})

    # transfer by owner
    tx_hash = c.transferFrom(someone, operator, SOMEONE_TOKEN_IDS[0], transact={"from": someone})

    logs = get_logs(tx_hash, c, "Transfer")

    assert len(logs) > 0
    args = logs[0].args
    assert args.sender == someone
    assert args.receiver == operator
    assert args.token_id == SOMEONE_TOKEN_IDS[0]
    assert c.ownerOf(SOMEONE_TOKEN_IDS[0]) == operator
    assert c.balanceOf(someone) == 2
    assert c.balanceOf(operator) == 2


def test_transferFrom_by_approved(c, w3, get_logs):
    someone, operator = w3.eth.accounts[1:3]

    # transfer by approved
    c.approve(operator, SOMEONE_TOKEN_IDS[1], transact={"from": someone})
    tx_hash = c.transferFrom(someone, operator, SOMEONE_TOKEN_IDS[1], transact={"from": operator})

    logs = get_logs(tx_hash, c, "Transfer")

    assert len(logs) > 0
    args = logs[0].args
    assert args.sender == someone
    assert args.receiver == operator
    assert args.token_id == SOMEONE_TOKEN_IDS[1]
    assert c.ownerOf(SOMEONE_TOKEN_IDS[1]) == operator
    assert c.balanceOf(someone) == 2
    assert c.balanceOf(operator) == 2


def test_transferFrom_by_operator(c, w3, get_logs):
    someone, operator = w3.eth.accounts[1:3]

    # transfer by operator
    c.setApprovalForAll(operator, True, transact={"from": someone})
    tx_hash = c.transferFrom(someone, operator, SOMEONE_TOKEN_IDS[2], transact={"from": operator})

    logs = get_logs(tx_hash, c, "Transfer")

    assert len(logs) > 0
    args = logs[0].args
    assert args.sender == someone
    assert args.receiver == operator
    assert args.token_id == SOMEONE_TOKEN_IDS[2]
    assert c.ownerOf(SOMEONE_TOKEN_IDS[2]) == operator
    assert c.balanceOf(someone) == 2
    assert c.balanceOf(operator) == 2


def test_safeTransferFrom_by_owner(c, w3, tx_failed, get_logs):
    someone, operator = w3.eth.accounts[1:3]

    # transfer from zero address
    with tx_failed():
        c.safeTransferFrom(ZERO_ADDRESS, operator, SOMEONE_TOKEN_IDS[0], transact={"from": someone})

    # transfer to zero address
    with tx_failed():
        c.safeTransferFrom(someone, ZERO_ADDRESS, SOMEONE_TOKEN_IDS[0], transact={"from": someone})

    # transfer token without ownership
    with tx_failed():
        c.safeTransferFrom(someone, operator, OPERATOR_TOKEN_ID, transact={"from": someone})

    # transfer invalid token
    with tx_failed():
        c.safeTransferFrom(someone, operator, INVALID_TOKEN_ID, transact={"from": someone})

    # transfer by owner
    tx_hash = c.safeTransferFrom(
        someone, operator, SOMEONE_TOKEN_IDS[0], transact={"from": someone}
    )

    logs = get_logs(tx_hash, c, "Transfer")

    assert len(logs) > 0
    args = logs[0].args
    assert args.sender == someone
    assert args.receiver == operator
    assert args.token_id == SOMEONE_TOKEN_IDS[0]
    assert c.ownerOf(SOMEONE_TOKEN_IDS[0]) == operator
    assert c.balanceOf(someone) == 2
    assert c.balanceOf(operator) == 2


def test_safeTransferFrom_by_approved(c, w3, get_logs):
    someone, operator = w3.eth.accounts[1:3]

    # transfer by approved
    c.approve(operator, SOMEONE_TOKEN_IDS[1], transact={"from": someone})
    tx_hash = c.safeTransferFrom(
        someone, operator, SOMEONE_TOKEN_IDS[1], transact={"from": operator}
    )

    logs = get_logs(tx_hash, c, "Transfer")

    assert len(logs) > 0
    args = logs[0].args
    assert args.sender == someone
    assert args.receiver == operator
    assert args.token_id == SOMEONE_TOKEN_IDS[1]
    assert c.ownerOf(SOMEONE_TOKEN_IDS[1]) == operator
    assert c.balanceOf(someone) == 2
    assert c.balanceOf(operator) == 2


def test_safeTransferFrom_by_operator(c, w3, get_logs):
    someone, operator = w3.eth.accounts[1:3]

    # transfer by operator
    c.setApprovalForAll(operator, True, transact={"from": someone})
    tx_hash = c.safeTransferFrom(
        someone, operator, SOMEONE_TOKEN_IDS[2], transact={"from": operator}
    )

    logs = get_logs(tx_hash, c, "Transfer")

    assert len(logs) > 0
    args = logs[0].args
    assert args.sender == someone
    assert args.receiver == operator
    assert args.token_id == SOMEONE_TOKEN_IDS[2]
    assert c.ownerOf(SOMEONE_TOKEN_IDS[2]) == operator
    assert c.balanceOf(someone) == 2
    assert c.balanceOf(operator) == 2


def test_safeTransferFrom_to_contract(c, w3, tx_failed, get_logs, get_contract):
    someone = w3.eth.accounts[1]

    # Can't transfer to a contract that doesn't implement the receiver code
    with tx_failed():
        c.safeTransferFrom(someone, c.address, SOMEONE_TOKEN_IDS[0], transact={"from": someone})

    # Only to an address that implements that function
    receiver = get_contract(
        """
@external
def onERC721Received(
        _operator: address,
        _from: address,
        _tokenId: uint256,
        _data: Bytes[1024]
    ) -> bytes4:
    return method_id("onERC721Received(address,address,uint256,bytes)", output_type=bytes4)
    """
    )
    tx_hash = c.safeTransferFrom(
        someone, receiver.address, SOMEONE_TOKEN_IDS[0], transact={"from": someone}
    )

    logs = get_logs(tx_hash, c, "Transfer")

    assert len(logs) > 0
    args = logs[0].args
    assert args.sender == someone
    assert args.receiver == receiver.address
    assert args.token_id == SOMEONE_TOKEN_IDS[0]
    assert c.ownerOf(SOMEONE_TOKEN_IDS[0]) == receiver.address
    assert c.balanceOf(someone) == 2
    assert c.balanceOf(receiver.address) == 1


def test_approve(c, w3, tx_failed, get_logs):
    someone, operator = w3.eth.accounts[1:3]

    # approve myself
    with tx_failed():
        c.approve(someone, SOMEONE_TOKEN_IDS[0], transact={"from": someone})

    # approve token without ownership
    with tx_failed():
        c.approve(operator, OPERATOR_TOKEN_ID, transact={"from": someone})

    # approve invalid token
    with tx_failed():
        c.approve(operator, INVALID_TOKEN_ID, transact={"from": someone})

    tx_hash = c.approve(operator, SOMEONE_TOKEN_IDS[0], transact={"from": someone})
    logs = get_logs(tx_hash, c, "Approval")

    assert len(logs) > 0
    args = logs[0].args
    assert args.owner == someone
    assert args.approved == operator
    assert args.token_id == SOMEONE_TOKEN_IDS[0]


def test_setApprovalForAll(c, w3, tx_failed, get_logs):
    someone, operator = w3.eth.accounts[1:3]
    approved = True

    # setApprovalForAll myself
    with tx_failed():
        c.setApprovalForAll(someone, approved, transact={"from": someone})

    tx_hash = c.setApprovalForAll(operator, approved, transact={"from": someone})
    logs = get_logs(tx_hash, c, "ApprovalForAll")

    assert len(logs) > 0
    args = logs[0].args
    assert args.owner == someone
    assert args.operator == operator
    assert args.approved == approved


def test_mint(c, w3, tx_failed, get_logs):
    minter, someone = w3.eth.accounts[:2]

    # mint by non-minter
    with tx_failed():
        c.mint(someone, SOMEONE_TOKEN_IDS[0], transact={"from": someone})

    # mint to zero address
    with tx_failed():
        c.mint(ZERO_ADDRESS, SOMEONE_TOKEN_IDS[0], transact={"from": minter})

    # mint by minter
    tx_hash = c.mint(someone, NEW_TOKEN_ID, transact={"from": minter})
    logs = get_logs(tx_hash, c, "Transfer")

    assert len(logs) > 0
    args = logs[0].args
    assert args.sender == ZERO_ADDRESS
    assert args.receiver == someone
    assert args.token_id == NEW_TOKEN_ID
    assert c.ownerOf(NEW_TOKEN_ID) == someone
    assert c.balanceOf(someone) == 4


def test_burn(c, w3, tx_failed, get_logs):
    someone, operator = w3.eth.accounts[1:3]

    # burn token without ownership
    with tx_failed():
        c.burn(SOMEONE_TOKEN_IDS[0], transact={"from": operator})

    # burn token by owner
    tx_hash = c.burn(SOMEONE_TOKEN_IDS[0], transact={"from": someone})
    logs = get_logs(tx_hash, c, "Transfer")

    assert len(logs) > 0
    args = logs[0].args
    assert args.sender == someone
    assert args.receiver == ZERO_ADDRESS
    assert args.token_id == SOMEONE_TOKEN_IDS[0]
    with tx_failed():
        c.ownerOf(SOMEONE_TOKEN_IDS[0])
    assert c.balanceOf(someone) == 2

import pytest


IDS = range(1, 65)


@pytest.fixture
def c(get_contract, w3):
    # a0, a1 own 1 token each
    owners = w3.eth.accounts[:3]
    # a2 owns 2 tokens
    owners.append(w3.eth.accounts[2])
    # a3 owns the rest
    owners.extend([w3.eth.accounts[3]] * 60)
    with open('examples/tokens/ERC721.vy') as f:
        return get_contract(
            f.read(),
            owners, IDS
        )


def test_balanceOf(c, w3):
    a0, a1, a2, a3, a4 = w3.eth.accounts[:5]
    # Correctly lists balances
    assert c.balanceOf(a0) == 1
    assert c.balanceOf(a1) == 1
    assert c.balanceOf(a2) == 2
    assert c.balanceOf(a3) == 60
    # Correctly reports account with no balance
    assert c.balanceOf(a4) == 0


def test_ownerOf(c, w3, assert_tx_failed):
    a0, a1, a2, a3 = w3.eth.accounts[:4]
    # Correctly finds ownership
    assert c.ownerOf(IDS[0]) == a0
    assert c.ownerOf(IDS[1]) == a1
    assert c.ownerOf(IDS[2]) == a2
    assert c.ownerOf(IDS[3]) == a2
    for _id in IDS[4:]:
        assert c.ownerOf(_id) == a3
    # Reverts for non-existant ID
    assert_tx_failed(lambda: c.ownerOf(99))


def test_approve(w3, c, assert_tx_failed):
    a0, a1, a2 = w3.eth.accounts[:3]
    # Approval can be given and taken away
    assert c.getApproved(IDS[0]) != a1
    c.approve(a1, IDS[0], transact={'from': a0})
    assert c.getApproved(IDS[0]) == a1
    c.approve(a2, IDS[0], transact={'from': a0})
    assert c.getApproved(IDS[0]) != a1
    # Can't approve something you don't own
    assert_tx_failed(lambda: c.approve(a1, IDS[1], transact={'from': a0}))


def test_approveAll(w3, c):
    a0, a1 = w3.eth.accounts[:2]

    assert not c.isApprovedForAll(a0, a1)
    c.setApprovalForAll(a1, True, transact={'from': a0})
    assert c.isApprovedForAll(a0, a1)
    c.setApprovalForAll(a1, False, transact={'from': a0})
    assert not c.isApprovedForAll(a0, a1)


def test_owner_transferFrom(w3, c, assert_tx_failed):
    a0, a1 = w3.eth.accounts[:2]

    # Basic transfer.
    c.transferFrom(a0, a1, IDS[0], transact={'from': a0})
    assert c.balanceOf(a0) == 0
    assert c.balanceOf(a1) == 2

    # Can't transfer one you don't own
    assert_tx_failed(lambda: c.transferFrom(a0, a1, IDS[0], transact={'from': a0}))


def test_approve_transferFrom(w3, c, assert_tx_failed):
    a0, a1, a2 = w3.eth.accounts[:3]

    # Approved transfer
    c.approve(a2, IDS[0], transact={'from': a0})
    c.transferFrom(a0, a1, IDS[0], transact={'from': a2})
    assert c.balanceOf(a0) == 0
    assert c.balanceOf(a1) == 2


def test_operator_transferFrom(w3, c, assert_tx_failed):
    a0, a1, a2 = w3.eth.accounts[:3]

    # Approved transfer
    c.setApprovalForAll(a2, True, transact={'from': a0})
    c.transferFrom(a0, a1, IDS[0], transact={'from': a2})
    assert c.balanceOf(a0) == 0
    assert c.balanceOf(a1) == 2


def test_account_safeTransferFrom(w3, c, assert_tx_failed):
    a0, a1 = w3.eth.accounts[:2]

    # Basic transfer.
    c.safeTransferFrom(a0, a1, IDS[0], transact={'from': a0})
    assert c.balanceOf(a0) == 0
    assert c.balanceOf(a1) == 2

    # Can't transfer one you don't own
    assert_tx_failed(lambda: c.safeTransferFrom(a0, a1, IDS[0], transact={'from': a0}))


def test_contract_safeTransferFrom(w3, c, assert_tx_failed, get_contract):
    a0, a1 = w3.eth.accounts[:2]

    # Can't transfer to a contract that doesn't implement the receiver code
    assert_tx_failed(lambda: c.safeTransferFrom(a0, c.address, IDS[0], transact={'from': a0}))

    # Only to an address that implements that function
    receiver = get_contract("""
@public
def onERC721Received(
        _operator: address,
        _from: address,
        _tokenId: uint256,
        _data: bytes[1024]
    ) -> bytes32:
    return method_id("onERC721Received(address,address,uint256,bytes)", bytes32)
    """)
    c.safeTransferFrom(a0, receiver.address, IDS[0], transact={'from': a0})

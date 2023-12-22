import pytest

# ERC1155 ownable, opensea compatible tests
# @author Dr. Pixel (github: @Doc-Pixel)

# constants - contract deployment
CONTRACT_NAME = "TEST 1155"
CONTRACT_SYMBOL = "T1155"

CONTRACT_URI = "https://mydomain.io/NFTdata/{id}"
NEW_CONTRACT_URI = "https://mynewdomain.io/NFTdata/{id}"
CONTRACT_METADATA_URI = "https://mydomain.io/NFTdata/collectionMetaData.json"
NEW_CONTRACT_METADATA_URI = "https://mydomain.io/NFTdata/newCollectionMetaData.json"

CONTRACT_DYNURI = "https://mydomain.io/NFTdata/"


ERC165_INTERFACE_ID = "0x01ffc9a7"
ERC1155_INTERFACE_ID = "0xd9b67a26"
ERC1155_INTERFACE_ID_METADATA = "0x0e89341c"
ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"
DUMMY_BYTES32_DATA = "0x0101010101010101010101010101010101010101010101010101010101010101"

# minting test lists
mintBatch = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
mintBatch2 = [11, 12, 13, 14, 15, 16, 17, 19, 19, 20]
minBatchSetOf10 = [1, 1, 1, 1, 1, 1, 1, 1, 1, 1]
mintConflictBatch = [1, 2, 3]


@pytest.fixture
def erc1155(get_contract, w3, tx_failed):
    owner, a1, a2, a3, a4, a5 = w3.eth.accounts[0:6]
    with open("examples/tokens/ERC1155ownable.vy") as f:
        code = f.read()
    c = get_contract(code, *[CONTRACT_NAME, CONTRACT_SYMBOL, CONTRACT_URI, CONTRACT_METADATA_URI])
    assert c.owner() == owner
    c.mintBatch(a1, mintBatch, minBatchSetOf10, transact={"from": owner})
    c.mintBatch(a3, mintBatch2, minBatchSetOf10, transact={"from": owner})

    assert c.balanceOf(a1, 1) == 1
    assert c.balanceOf(a1, 2) == 1
    assert c.balanceOf(a1, 3) == 1
    with tx_failed():
        c.mintBatch(ZERO_ADDRESS, mintBatch, minBatchSetOf10, transact={"from": owner})
    with tx_failed():
        c.mintBatch(a1, [1, 2, 3], [1, 1], transact={"from": owner})

    c.mint(a1, 21, 1, transact={"from": owner})
    c.mint(a1, 22, 1, transact={"from": owner})
    c.mint(a1, 23, 1, transact={"from": owner})
    c.mint(a1, 24, 1, transact={"from": owner})

    with tx_failed():
        c.mint(a1, 24, 1, transact={"from": a3})
    with tx_failed():
        c.mint(ZERO_ADDRESS, 24, 1, transact={"from": owner})

    assert c.balanceOf(a1, 21) == 1
    assert c.balanceOf(a1, 22) == 1
    assert c.balanceOf(a1, 23) == 1
    assert c.balanceOf(a1, 24) == 1

    return c


# tests


def test_initial_state(erc1155):
    # Check if the constructor of the contract is set up properly
    # and the contract is deployed with the desired variables

    # variables set correctly?
    assert erc1155.name() == CONTRACT_NAME
    assert erc1155.symbol() == CONTRACT_SYMBOL
    assert erc1155.uri(0) == CONTRACT_URI

    # interfaces set up correctly?
    assert erc1155.supportsInterface(ERC165_INTERFACE_ID)
    assert erc1155.supportsInterface(ERC1155_INTERFACE_ID)
    assert erc1155.supportsInterface(ERC1155_INTERFACE_ID_METADATA)


def test_pause(erc1155, w3, tx_failed):
    owner, a1, a2, a3, a4, a5 = w3.eth.accounts[0:6]
    # check the pause status, pause, check, unpause, check, with owner and non-owner w3.eth.accounts
    # this test will check all the function that should not work when paused.
    assert not erc1155.paused()

    # try to pause the contract from a non owner account
    with tx_failed():
        erc1155.pause(transact={"from": a1})

    # now pause the contract and check status
    erc1155.pause(transact={"from": owner})
    assert erc1155.paused()

    # try pausing a paused contract
    with tx_failed():
        erc1155.pause()

    # try functions that should not work when paused
    with tx_failed():
        erc1155.setURI(NEW_CONTRACT_URI)

    # test burn and burnbatch
    with tx_failed():
        erc1155.burn(21, 1)
    with tx_failed():
        erc1155.burnBatch([21, 22], [1, 1])

    # check mint and mintbatch
    with tx_failed():
        erc1155.mint(a1, 21, 1, transact={"from": owner})
    with tx_failed():
        erc1155.mintBatch(a1, mintBatch, minBatchSetOf10, transact={"from": owner})

    # check safetransferfrom and safebatchtransferfrom
    with tx_failed():
        erc1155.safeTransferFrom(a1, a2, 21, 1, DUMMY_BYTES32_DATA, transact={"from": a1})
    with tx_failed():
        erc1155.safeBatchTransferFrom(
            a1, a2, [21, 22, 23], [1, 1, 1], DUMMY_BYTES32_DATA, transact={"from": a1}
        )

    # check ownership functions
    with tx_failed():
        erc1155.transferOwnership(a1)
    with tx_failed():
        erc1155.renounceOwnership()

    # check approval functions
    with tx_failed():
        erc1155.setApprovalForAll(owner, a5, True)

    # try and unpause as non-owner
    with tx_failed():
        erc1155.unpause(transact={"from": a1})

    erc1155.unpause(transact={"from": owner})
    assert not erc1155.paused()

    # try un pausing an unpaused contract
    with tx_failed():
        erc1155.unpause()


def test_contractURI(erc1155, w3, tx_failed):
    owner, a1, a2, a3, a4, a5 = w3.eth.accounts[0:6]
    # change contract URI and restore.
    assert erc1155.contractURI() == CONTRACT_METADATA_URI
    with tx_failed():
        erc1155.setContractURI(NEW_CONTRACT_METADATA_URI, transact={"from": a1})
    erc1155.setContractURI(NEW_CONTRACT_METADATA_URI, transact={"from": owner})
    assert erc1155.contractURI() == NEW_CONTRACT_METADATA_URI
    assert erc1155.contractURI() != CONTRACT_METADATA_URI
    erc1155.setContractURI(CONTRACT_METADATA_URI, transact={"from": owner})
    assert erc1155.contractURI() != NEW_CONTRACT_METADATA_URI
    assert erc1155.contractURI() == CONTRACT_METADATA_URI

    with tx_failed():
        erc1155.setContractURI(CONTRACT_METADATA_URI)


def test_URI(erc1155, w3, tx_failed):
    owner, a1, a2, a3, a4, a5 = w3.eth.accounts[0:6]
    # change contract URI and restore.
    assert erc1155.uri(0) == CONTRACT_URI
    erc1155.setURI(NEW_CONTRACT_URI, transact={"from": owner})
    assert erc1155.uri(0) == NEW_CONTRACT_URI
    assert erc1155.uri(0) != CONTRACT_URI
    erc1155.setURI(CONTRACT_URI, transact={"from": owner})
    assert erc1155.uri(0) != NEW_CONTRACT_URI
    assert erc1155.uri(0) == CONTRACT_URI

    with tx_failed():
        erc1155.setURI(CONTRACT_URI)

    # set contract to dynamic URI
    erc1155.toggleDynUri(True, transact={"from": owner})
    erc1155.setURI(CONTRACT_DYNURI, transact={"from": owner})
    assert erc1155.uri(0) == CONTRACT_DYNURI + str(0) + ".json"


def test_safeTransferFrom_balanceOf_single(erc1155, w3, tx_failed):
    owner, a1, a2, a3, a4, a5 = w3.eth.accounts[0:6]
    assert erc1155.balanceOf(a1, 24) == 1
    # transfer by non-owner
    with tx_failed():
        erc1155.safeTransferFrom(a1, a2, 24, 1, DUMMY_BYTES32_DATA, transact={"from": a2})

    # transfer to zero address
    with tx_failed():
        erc1155.safeTransferFrom(a1, ZERO_ADDRESS, 24, 1, DUMMY_BYTES32_DATA, transact={"from": a1})

    # transfer to self
    with tx_failed():
        erc1155.safeTransferFrom(a1, a1, 24, 1, DUMMY_BYTES32_DATA, transact={"from": a1})

    # transfer more than owned
    with tx_failed():
        erc1155.safeTransferFrom(a1, a2, 24, 500, DUMMY_BYTES32_DATA, transact={"from": a1})

    # transfer item not owned / not existing
    with tx_failed():
        erc1155.safeTransferFrom(a1, a2, 500, 1, DUMMY_BYTES32_DATA, transact={"from": a1})

    erc1155.safeTransferFrom(a1, a2, 21, 1, DUMMY_BYTES32_DATA, transact={"from": a1})

    assert erc1155.balanceOf(a2, 21) == 1

    # try to transfer item again
    with tx_failed():
        erc1155.safeTransferFrom(a1, a2, 21, 1, DUMMY_BYTES32_DATA, transact={"from": a1})
    assert erc1155.balanceOf(a1, 21) == 0


# TODO: mint 20 NFTs [1:20] and check the balance for each
def test_mintBatch_balanceOf(erc1155, w3, tx_failed):  # test_mint_batch
    owner, a1, a2, a3, a4, a5 = w3.eth.accounts[0:6]
    # Use the mint three fixture to mint the tokens.
    # this test checks the balances of this test
    for i in range(1, 10):
        assert erc1155.balanceOf(a1, i) == 1


def test_safeBatchTransferFrom_balanceOf_batch(erc1155, w3, tx_failed):  # test_mint_batch
    owner, a1, a2, a3, a4, a5 = w3.eth.accounts[0:6]

    # check a1 balances for NFTs 21-24
    assert erc1155.balanceOf(a1, 21) == 1
    assert erc1155.balanceOf(a1, 22) == 1
    assert erc1155.balanceOf(a1, 23) == 1
    assert erc1155.balanceOf(a1, 23) == 1

    # try to transfer item from non-item owner account
    with tx_failed():
        erc1155.safeBatchTransferFrom(
            a1, a2, [21, 22, 23], [1, 1, 1], DUMMY_BYTES32_DATA, transact={"from": a2}
        )

    # try to transfer item to zero address
    with tx_failed():
        erc1155.safeBatchTransferFrom(
            a1, ZERO_ADDRESS, [21, 22, 23], [1, 1, 1], DUMMY_BYTES32_DATA, transact={"from": a1}
        )

    # try to transfer item to self
    with tx_failed():
        erc1155.safeBatchTransferFrom(
            a1, a1, [21, 22, 23], [1, 1, 1], DUMMY_BYTES32_DATA, transact={"from": a1}
        )

    # try to transfer more items than we own
    with tx_failed():
        erc1155.safeBatchTransferFrom(
            a1, a2, [21, 22, 23], [1, 125, 1], DUMMY_BYTES32_DATA, transact={"from": a1}
        )

    # mismatched item and amounts
    with tx_failed():
        erc1155.safeBatchTransferFrom(
            a1, a2, [21, 22, 23], [1, 1], DUMMY_BYTES32_DATA, transact={"from": a1}
        )

    # try to transfer nonexisting item
    with tx_failed():
        erc1155.safeBatchTransferFrom(
            a1, a2, [21, 22, 500], [1, 1, 1], DUMMY_BYTES32_DATA, transact={"from": a1}
        )
    assert erc1155.safeBatchTransferFrom(
        a1, a2, [21, 22, 23], [1, 1, 1], DUMMY_BYTES32_DATA, transact={"from": a1}
    )

    # try to transfer again, our balances are zero now, should fail
    with tx_failed():
        erc1155.safeBatchTransferFrom(
            a1, a2, [21, 22, 23], [1, 1, 1], DUMMY_BYTES32_DATA, transact={"from": a1}
        )
    with tx_failed():
        erc1155.balanceOfBatch([a2, a2, a2], [21, 22], transact={"from": owner})

    assert erc1155.balanceOfBatch([a2, a2, a2], [21, 22, 23]) == [1, 1, 1]
    assert erc1155.balanceOf(a1, 21) == 0


def test_mint_one_burn_one(erc1155, w3, tx_failed):
    owner, a1, a2, a3, a4, a5 = w3.eth.accounts[0:6]

    # check the balance from an owner and non-owner account
    erc1155.mint(owner, 25, 1, transact={"from": owner})

    assert erc1155.balanceOf(owner, 25) == 1
    assert erc1155.balanceOf(owner, 25) == 1

    # try and burn an item we don't control
    with tx_failed():
        erc1155.burn(25, 1, transact={"from": a3})

    # burn an item that contains something we don't own
    with tx_failed():
        erc1155.burn(595, 1, transact={"from": a1})

    # burn ah item passing a higher amount than we own
    with tx_failed():
        erc1155.burn(25, 500, transact={"from": a1})

    erc1155.burn(25, 1, transact={"from": owner})

    assert erc1155.balanceOf(owner, 25) == 0


def test_mint_batch_burn_batch(erc1155, w3, tx_failed):
    owner, a1, a2, a3, a4, a5 = w3.eth.accounts[0:6]
    # mint NFTs 11-20

    # check the balance
    assert erc1155.balanceOfBatch([a3, a3, a3], [11, 12, 13]) == [1, 1, 1]

    # try and burn a batch we don't control
    with tx_failed():
        erc1155.burnBatch([11, 12], [1, 1])

    # ids and amounts array length not matching
    with tx_failed():
        erc1155.burnBatch([1, 2, 3], [1, 1], transact={"from": a1})

    # burn a batch that contains something we don't own
    with tx_failed():
        erc1155.burnBatch([2, 3, 595], [1, 1, 1], transact={"from": a1})

    # burn a batch passing a higher amount than we own
    with tx_failed():
        erc1155.burnBatch([1, 2, 3], [1, 500, 1], transact={"from": a1})

    # burn existing
    erc1155.burnBatch([11, 12], [1, 1], transact={"from": a3})

    assert erc1155.balanceOfBatch([a3, a3, a3], [11, 12, 13]) == [0, 0, 1]

    # burn again, should revert
    with tx_failed():
        erc1155.burnBatch([11, 12], [1, 1], transact={"from": a3})

    assert erc1155.balanceOfBatch([a3, a3, a3], [1, 2, 3]) == [0, 0, 0]


def test_approval_functions(erc1155, w3, tx_failed):  # test_mint_batch
    owner, a1, a2, a3, a4, a5 = w3.eth.accounts[0:6]
    # self-approval by the owner
    with tx_failed():
        erc1155.setApprovalForAll(a5, a5, True, transact={"from": a5})

    # let's approve and operator for somebody else's account
    with tx_failed():
        erc1155.setApprovalForAll(owner, a5, True, transact={"from": a3})

    # set approval correctly
    erc1155.setApprovalForAll(owner, a5, True)

    # check approval
    erc1155.isApprovedForAll(owner, a5)

    # remove approval
    erc1155.setApprovalForAll(owner, a5, False)


def test_max_batch_size_violation(erc1155, w3, tx_failed):
    owner, a1, a2, a3, a4, a5 = w3.eth.accounts[0:6]
    TOTAL_BAD_BATCH = 200
    ids = []
    amounts = []
    for i in range(1, TOTAL_BAD_BATCH):
        ids.append(i)
        amounts.append(1)

    with tx_failed():
        erc1155.mintBatch(a1, ids, amounts, transact={"from": owner})


# Transferring back and forth


def test_ownership_functions(erc1155, w3, tx_failed, tester):
    owner, a1, a2, a3, a4, a5 = w3.eth.accounts[0:6]
    print(owner, a1, a2)
    print("___owner___", erc1155.owner())
    # change owner from account 0 to account 1 and back

    assert erc1155.owner() == owner
    with tx_failed():
        erc1155.transferOwnership(a1, transact={"from": a2})

    # try to transfer ownership to current owner
    with tx_failed():
        erc1155.transferOwnership(owner)
    # try to transfer ownership to ZERO ADDRESS
    with tx_failed():
        erc1155.transferOwnership("0x0000000000000000000000000000000000000000")

    # Transfer ownership to account 1
    erc1155.transferOwnership(a1, transact={"from": owner})
    # assert erc1155.owner() == a1
    assert erc1155.owner() == a1


def test_renounce_ownership(erc1155, w3, tx_failed):
    owner, a1, a2, a3, a4, a5 = w3.eth.accounts[0:6]
    assert erc1155.owner() == owner
    # try to transfer ownership from non-owner account
    with tx_failed():
        erc1155.renounceOwnership(transact={"from": a2})

    erc1155.renounceOwnership(transact={"from": owner})

    # assert erc1155.owner() == ZERO_ADDRESS

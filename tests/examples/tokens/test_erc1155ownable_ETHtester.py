import pytest
# ERC1155 ownable, opensea compatible tests
# @author Dr. Pixel (github: @Doc-Pixel)

# constants - contract deployment
CONTRACT_NAME = 'TEST 1155'
CONTRACT_SYMBOL= 'T1155'
CONTRACT_URI = 'https://mydomain.io/NFTdata/{id}'
NEW_CONTRACT_URI = 'https://mynewdomain.io/NFTdata/{id}'
ERC165_INTERFACE_ID = '0x01ffc9a7'
ERC1155_INTERFACE_ID = '0xd9b67a26'
ERC1155_INTERFACE_ID_METADATA = '0x0e89341c'
ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"

# minting test lists
mintBatch = [1,2,3,4,5,6,7,8,9,10]
mintBatch2 = [11,12,13,14,15,16,17,19,19,20]
minBatchSetOf10 = [1,1,1,1,1,1,1,1,1,1]
mintConflictBatch = [1,2,3]

@pytest.fixture
def NFT_contract(get_contract, w3):
    owner, a1, a2 = w3.eth.accounts[0:3]
    with open("examples/tokens/ERC1155ownable.vy") as f:
        code = f.read()
    c = get_contract(code, *[CONTRACT_NAME, CONTRACT_SYMBOL, CONTRACT_URI])
    return c

##### test fixtures #####

@pytest.fixture
def test_mint(NFT_contract, w3, assert_tx_failed):
    NFT_contract.mint(w3.eth.accounts[1], 1, 1, '')
    NFT_contract.mint(w3.eth.accounts[1], 2, 1, '')
    NFT_contract.mint(w3.eth.accounts[1], 3, 1, '')
    
    assert_tx_failed(lambda: NFT_contract.mint(w3.eth.accounts[1], 4, 1, '', transact={"from": w3.eth.accounts[3]}))
    assert_tx_failed(lambda: NFT_contract.mint(ZERO_ADDRESS, 4, 1, '', transact={"from": w3.eth.accounts[0]}))

    assert (lambda: NFT_contract.balanceOf(w3.eth.accounts[1],1) == 1)
    assert (lambda: NFT_contract.balanceOf(w3.eth.accounts[1],2) == 1)
    assert (lambda: NFT_contract.balanceOf(w3.eth.accounts[1],3) == 1)

    # check ZERO_ADDRESS balance (should fail)
    assert_tx_failed(lambda: NFT_contract.balanceOf(ZERO_ADDRESS,3) == 1)


@pytest.fixture
def test_mint_batch(NFT_contract, w3, assert_tx_failed):
    NFT_contract.mintBatch(w3.eth.accounts[1], mintBatch, minBatchSetOf10, '')
    NFT_contract.mintBatch(w3.eth.accounts[3], mintBatch2, minBatchSetOf10, '')
    # assert_tx_failed(lambda: NFT_contract.mintBatch(w3.eth.accounts[1], mintBatch, minBatchSetOf10, '', transact={"from": w3.eth.accounts[2]}))
    assert (lambda: NFT_contract.balanceOf(w3.eth.accounts[1],1) == 1)
    assert (lambda: NFT_contract.balanceOf(w3.eth.accounts[1],2) == 1)
    assert (lambda: NFT_contract.balanceOf(w3.eth.accounts[1],3) == 1)
    assert_tx_failed(lambda: NFT_contract.mintBatch(ZERO_ADDRESS, mintBatch, minBatchSetOf10, ''))
    assert_tx_failed(lambda: NFT_contract.mintBatch(w3.eth.accounts[1], [1,2,3], [1,1], ''))


##### tests #####

def test_initial_state(NFT_contract):
    # Check if the constructor of the contract is set up properly
    # and the contract is deployed with the desired variables

    # variables set correctly?
    assert NFT_contract.name() == CONTRACT_NAME
    assert NFT_contract.symbol() == CONTRACT_SYMBOL
    assert NFT_contract.uri() == CONTRACT_URI

    # interfaces set up correctly?
    assert NFT_contract.supportsInterface(ERC165_INTERFACE_ID) 
    assert NFT_contract.supportsInterface(ERC1155_INTERFACE_ID) 
    assert NFT_contract.supportsInterface(ERC1155_INTERFACE_ID_METADATA) 
    

def test_pause(NFT_contract,w3, assert_tx_failed):
    # check the pause status, pause, check, unpause, check, with owner and non-owner w3.eth.accounts
    # this test will check all the function that should not work when paused.
    assert NFT_contract.paused() == False
    
    # try to pause the contract from a non owner account
    assert_tx_failed(lambda: NFT_contract.pause(transact={"from": w3.eth.accounts[1]}))
    
    # now pause the contract and check status
    NFT_contract.pause(transact={"from": w3.eth.accounts[0]})
    assert NFT_contract.paused() == True
    
    # try pausing a paused contract
    assert_tx_failed(lambda: NFT_contract.pause())
    
    # try functions that should not work when paused
    assert_tx_failed(lambda: NFT_contract.setURI(NEW_CONTRACT_URI))

    # test burn and burnbatch    
    assert_tx_failed(lambda: NFT_contract.burn(1,1))
    assert_tx_failed(lambda: NFT_contract.burnBatch([1,2],[1,1]))

    # check mint and mintbatch
    assert_tx_failed(lambda: NFT_contract.mint(w3.eth.accounts[1], 1, 1, '', transact={"from": w3.eth.accounts[0]}))
    assert_tx_failed(lambda: NFT_contract.mintBatch(w3.eth.accounts[1], mintBatch, minBatchSetOf10, '', transact={"from": w3.eth.accounts[0]}))

    # check safetransferfrom and safebatchtransferfrom
    assert_tx_failed(lambda: NFT_contract.safeTransferFrom(w3.eth.accounts[1], w3.eth.accounts[2], 1, 1, '', transact={"from": w3.eth.accounts[1]}))
    assert_tx_failed(lambda: NFT_contract.safeBatchTransferFrom(w3.eth.accounts[1], w3.eth.accounts[2], [1,2,3], [1,1,1], '', transact={"from": w3.eth.accounts[1]}))

    # check ownership functions
    assert_tx_failed(lambda: NFT_contract.transferOwnership(w3.eth.accounts[1]))
    assert_tx_failed(lambda: NFT_contract.renounceOwnership())

    # check approval functions
    assert_tx_failed(lambda: NFT_contract.setApprovalForAll(w3.eth.accounts[0],w3.eth.accounts[5],True))
    assert_tx_failed(lambda: NFT_contract.isApprovedForAll(w3.eth.accounts[0],w3.eth.accounts[5]))

    # try and unpause as non-owner
    assert_tx_failed(lambda: NFT_contract.unpause(transact={"from": w3.eth.accounts[1]}))

    NFT_contract.unpause(transact={"from": w3.eth.accounts[0]})
    assert NFT_contract.paused() == False

    # try un pausing an unpaused contract
    assert_tx_failed(lambda: NFT_contract.unpause())


def test_URI(NFT_contract, w3,assert_tx_failed):
    # change contract URI and restore.
    assert NFT_contract.uri() == CONTRACT_URI
    NFT_contract.setURI(NEW_CONTRACT_URI, transact={"from": w3.eth.accounts[1]})
    assert NFT_contract.uri() == NEW_CONTRACT_URI
    assert NFT_contract.uri() != CONTRACT_URI
    NFT_contract.setURI(CONTRACT_URI, transact={"from": w3.eth.accounts[1]})
    assert NFT_contract.uri() != NEW_CONTRACT_URI
    assert NFT_contract.uri() == CONTRACT_URI

    assert_tx_failed(lambda: NFT_contract.setURI(CONTRACT_URI))

def test_safeTransferFrom_balanceOf_single(NFT_contract, w3, test_mint, assert_tx_failed):
    # transfer NFT 1 from account 1 to account 2 use test_mint_single fixture
    NFT_contract.mint(w3.eth.accounts[1], 4, 1, '', transact={"from": w3.eth.accounts[0]})
    assert (lambda: NFT_contract.balanceOf(w3.eth.accounts[1],4, transact={"from": w3.eth.accounts[1]}) == 1)
    
    # transfer by non-owner
    assert_tx_failed(lambda: NFT_contract.safeTransferFrom(w3.eth.accounts[1], w3.eth.accounts[2], 4, 1, '', transact={"from": w3.eth.accounts[2]}))
    
    # transfer to zero address
    assert_tx_failed(lambda: NFT_contract.safeTransferFrom(w3.eth.accounts[1], ZERO_ADDRESS, 4, 1, '', transact={"from": w3.eth.accounts[1]}))
    
    # transfer to self
    assert_tx_failed(lambda: NFT_contract.safeTransferFrom(w3.eth.accounts[1], w3.eth.accounts[1], 4, 1, '', transact={"from": w3.eth.accounts[1]}))
    
    # transfer more than owned
    assert_tx_failed(lambda: NFT_contract.safeTransferFrom(w3.eth.accounts[1], w3.eth.accounts[2], 4, 500, '', transact={"from": w3.eth.accounts[1]}))
    
    # transfer item not owned / not existing
    assert_tx_failed(lambda: NFT_contract.safeTransferFrom(w3.eth.accounts[1], w3.eth.accounts[2], 500, 1, '', transact={"from": w3.eth.accounts[1]}))
    
    NFT_contract.mint(w3.eth.accounts[1], 21, 1, '', transact={"from": w3.eth.accounts[0]})
    NFT_contract.safeTransferFrom(w3.eth.accounts[1], w3.eth.accounts[2], 21, 1, '', transact={"from": w3.eth.accounts[1]})
    
    assert (lambda: NFT_contract.balanceOf(w3.eth.accounts[2],1, transact={"from": w3.eth.accounts[0]}) == 1)
    
    # try to transfer item again
    assert_tx_failed(lambda: NFT_contract.safeTransferFrom(w3.eth.accounts[1], w3.eth.accounts[2], 21, 1, '', transact={"from": w3.eth.accounts[1]}))
    assert (lambda: NFT_contract.balanceOf(w3.eth.accounts[1],1, {"from": w3.eth.w3.eth.accounts[0]}) == 0)
    

# TODO: mint 20 NFTs [1:20] and check the balance for each
def test_mintBatch_balanceOf(NFT_contract, w3, test_mint_batch, assert_tx_failed):
    # Use the mint three fixture to mint the tokens. 
    # this test checks the balances of this test
    for i in range (1,10):
        assert (lambda: NFT_contract.balanceOf(w3.eth.accounts[1], i, transact={"from": w3.eth.accounts[1]}) == 1)
        assert_tx_failed(lambda: NFT_contract.balanceOf(ZERO_ADDRESS, i, transact={"from": w3.eth.accounts[1]}) == 1)
    
def test_safeBatchTransferFrom_balanceOf_batch(NFT_contract, w3, test_mint_batch, assert_tx_failed):
    # transfer NFT 1 from account 1 to account 2 use test_mint_single fixture

    NFT_contract.balanceOf(w3.eth.accounts[1],1, transact={"from": w3.eth.accounts[1]}) == 1
    

    # try to transfer item from non item owner account
    assert_tx_failed(lambda: NFT_contract.safeBatchTransferFrom(w3.eth.accounts[1], w3.eth.accounts[2], [1,2,3], [1,1,1], '', transact={"from": w3.eth.accounts[2]}))

    # try to transfer item to zero address
    assert_tx_failed(lambda: NFT_contract.safeBatchTransferFrom(w3.eth.accounts[1], ZERO_ADDRESS, [1,2,3], [1,1,1], '', transact={"from": w3.eth.accounts[1]}))

    # try to transfer item to self
    assert_tx_failed(lambda: NFT_contract.safeBatchTransferFrom(w3.eth.accounts[1], w3.eth.accounts[1], [1,2,3], [1,1,1], '', transact={"from": w3.eth.accounts[1]}))
    
    # try to transfer more items than we own
    assert_tx_failed(lambda: NFT_contract.safeBatchTransferFrom(w3.eth.accounts[1], w3.eth.accounts[2], [1,2,3], [1,125,1], '', transact={"from": w3.eth.accounts[1]}))

    # mismatched item and amounts
    assert_tx_failed(lambda: NFT_contract.safeBatchTransferFrom(w3.eth.accounts[1], w3.eth.accounts[2], [1,2,3], [1,1], '', transact={"from": w3.eth.accounts[1]}))

    # try to transfer nonexisting item
    assert_tx_failed(lambda: NFT_contract.safeBatchTransferFrom(w3.eth.accounts[1], w3.eth.accounts[2], [1,2,500], [1,1,1], '', transact={"from": w3.eth.accounts[1]}))
    assert (lambda: NFT_contract.safeBatchTransferFrom(w3.eth.accounts[1], w3.eth.accounts[2], [1,2,3], [1,1,1], '', transact={"from": w3.eth.accounts[1]}))
    
    # try to transfer again, our balances are zero now, should fail
    assert_tx_failed(lambda: NFT_contract.safeBatchTransferFrom(w3.eth.accounts[1], w3.eth.accounts[2], [1,2,3], [1,1,1], '', transact={"from": w3.eth.accounts[1]}))
    assert_tx_failed(lambda: NFT_contract.balanceOfBatch([w3.eth.accounts[2],w3.eth.accounts[2],w3.eth.accounts[2]],[1,2], transact={"from": w3.eth.accounts[0]}) == [1,1,1])
        
    assert (lambda: NFT_contract.balanceOfBatch([w3.eth.accounts[2],w3.eth.accounts[2],w3.eth.accounts[2]],[1,2,3], transact={"from": w3.eth.accounts[0]}) == [1,1,1])
    assert (lambda: NFT_contract.balanceOf(w3.eth.accounts[1],1, transact={"from": w3.eth.accounts[0]}) == 0)

def test_mint_one_burn_one(NFT_contract, w3, assert_tx_failed):
    # check the balance from an owner and non-owner account 
 
    NFT_contract.mint(w3.eth.accounts[0], 21, 1, '', transact={"from": w3.eth.accounts[0]})

    assert (lambda: NFT_contract.balanceOf(w3.eth.accounts[0],21, transact={"from": w3.eth.accounts[0]}) == 1)
    assert (lambda: NFT_contract.balanceOf(w3.eth.accounts[0],21, transact={"from": w3.eth.accounts[1]}) == 1)

    # try and burn an item we don't control
    assert_tx_failed(lambda: NFT_contract.burn(21,1,transact={"from": w3.eth.accounts[3]}))

    # burn an item that contains something we don't own
    assert_tx_failed(lambda: NFT_contract.burn(595,1,transact={"from": w3.eth.accounts[1]}))

    # burn ah item passing a higher amount than we own
    assert_tx_failed(lambda: NFT_contract.burn(21,500,transact={"from": w3.eth.accounts[1]}))

    NFT_contract.burn(21,1, transact={"from": w3.eth.accounts[0]})

    assert (lambda: NFT_contract.balanceOf(w3.eth.accounts[0],21, transact={"from": w3.eth.accounts[1]}) == 0)


def test_mint_batch_burn_batch(NFT_contract, w3, assert_tx_failed):
    # mint NFTs 11-20
    NFT_contract.mintBatch(w3.eth.accounts[3], mintBatch2, minBatchSetOf10, '',transact={"from": w3.eth.accounts[0]})

    # check the balance
    assert (lambda: NFT_contract.balanceOfBatch([w3.eth.accounts[1],w3.eth.accounts[1],w3.eth.accounts[1]],[1,2,3], transact={"from": w3.eth.accounts[1]}) == [1,1,1])

    # try and burn a batch we don't control
    assert_tx_failed(lambda: NFT_contract.burnBatch([11,12],[1,1]))

    # ids and amounts array length not matching
    assert_tx_failed(lambda: NFT_contract.burnBatch([1,2,3],[1,1], transact={"from": w3.eth.accounts[1]}))

    # burn a batch that contains something we don't own
    assert_tx_failed(lambda: NFT_contract.burnBatch([2,3,595],[1,1,1],transact={"from": w3.eth.accounts[1]}))

    # burn a batch passing a higher amount than we own
    assert_tx_failed(lambda: NFT_contract.burnBatch([1,2,3],[1,500,1],transact={"from": w3.eth.accounts[1]}))

    # burn existing
    NFT_contract.burnBatch([11,12],[1,1],transact={"from": w3.eth.accounts[3]})

    assert (lambda: NFT_contract.balanceOfBatch([w3.eth.accounts[1],w3.eth.accounts[1],w3.eth.accounts[1]],[11,12,13], transact={"from": w3.eth.accounts[1]}) == [0,0,1])

    # burn again, should revert
    assert_tx_failed(lambda: NFT_contract.burnBatch([1,2],[1,1],transact={"from": w3.eth.accounts[1]}))

    assert (lambda: NFT_contract.balanceOfBatch([w3.eth.accounts[1],w3.eth.accounts[1],w3.eth.accounts[1]],[1,2,3], transact={"from": w3.eth.accounts[1]}) == [0,0,1])


def test_approval_functions(NFT_contract, w3, test_mint_batch, assert_tx_failed):

    # self-approval by the owner
    assert_tx_failed(lambda: NFT_contract.setApprovalForAll(w3.eth.accounts[5],w3.eth.accounts[5],True, transact={"from": w3.eth.accounts[5]}))

    # let's approve and operator for somebody else's account
    assert_tx_failed(lambda: NFT_contract.setApprovalForAll(w3.eth.accounts[0],w3.eth.accounts[5],True, transact={"from": w3.eth.accounts[3]}))

    # set approval correctly
    NFT_contract.setApprovalForAll(w3.eth.accounts[0],w3.eth.accounts[5],True)

    # check approval
    NFT_contract.isApprovedForAll(w3.eth.accounts[0],w3.eth.accounts[5])

    # remove approval
    NFT_contract.setApprovalForAll(w3.eth.accounts[0],w3.eth.accounts[5],False)


def test_max_batch_size_violation(NFT_contract, w3, assert_tx_failed):
    TOTAL_BAD_BATCH = 200
    ids = []
    amounts = []
    for i in range(1,TOTAL_BAD_BATCH):
        ids.append(i)
        amounts.append(1)

    assert_tx_failed(lambda: NFT_contract.mintBatch(w3.eth.accounts[1], ids, amounts, '', transact={"from": w3.eth.accounts[0]}))


# Transferring back and forth

def test_ownership_functions(NFT_contract, w3, assert_tx_failed,tester):
    owner, a1, a2 = w3.eth.accounts[0:3]
    print(owner,a1,a2)
    print('___owner___', NFT_contract.owner())
    # change owner from account 0 to account 1 and back
    
    assert NFT_contract.owner() == owner
    assert_tx_failed(lambda: NFT_contract.transferOwnership(w3.eth.accounts[1], transact={"from": a2}))
    
    # try to transfer ownership to current owner
    assert_tx_failed(lambda: NFT_contract.transferOwnership(w3.eth.accounts[0]))
    # try to transfer ownership to ZERO ADDRESS
    assert_tx_failed(lambda: NFT_contract.transferOwnership("0x0000000000000000000000000000000000000000"))

    # Transfer ownership to account 1    
    NFT_contract.transferOwnership(w3.eth.accounts[1])
    assert (lambda: NFT_contract.owner() == w3.eth.accounts[1])

def test_renounce_ownership(NFT_contract, w3, assert_tx_failed):
    
    assert NFT_contract.owner() == w3.eth.accounts[0]
    # try to transfer ownership from non-owner account
    assert_tx_failed(lambda: NFT_contract.renounceOwnership(transact={"from": w3.eth.accounts[2]}))

    NFT_contract.renounceOwnership(transact={"from": w3.eth.accounts[0]})

    assert NFT_contract.owner() == None
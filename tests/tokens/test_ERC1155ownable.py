
# brownie test
import pytest
import brownie
from brownie import ZERO_ADDRESS, accounts
from web3.exceptions import ValidationError

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

# minting test lists
mintBatch = [1,2,3,4,5,6,7,8,9,10]
mintBatch2 = [11,12,13,14,15,16,17,19,19,20]
minBatchSetOf10 = [1,1,1,1,1,1,1,1,1,1]
mintConflictBatch = [1,2,3]

##### test fixtures #####
@pytest.fixture
def NFT_contract(ERC1155ownable, accounts, scope="module", autouse=True):
    yield accounts[0].deploy(ERC1155ownable, CONTRACT_NAME, CONTRACT_SYMBOL, CONTRACT_URI)

@pytest.fixture(autouse=True)
def isolation(fn_isolation):
    pass

@pytest.fixture
def test_mint(NFT_contract):
    NFT_contract.mint(accounts[1], 1, 1, '', {"from": accounts[0]})
    NFT_contract.mint(accounts[1], 2, 1, '', {"from": accounts[0]})
    NFT_contract.mint(accounts[1], 3, 1, '', {"from": accounts[0]})
    
    with brownie.reverts():
        # mint with non-owner
        NFT_contract.mint(accounts[1], 4, 1, '', {"from": accounts[3]})
    # assert_tx_failed(NFT_contract.mint(accounts[1], 4, 1, '', {"from": accounts[3]}))
    with brownie.reverts():
        # mint to zero address
        NFT_contract.mint(ZERO_ADDRESS, 4, 1, '', {"from": accounts[0]})


@pytest.fixture
def test_mint_batch(NFT_contract):
    NFT_contract.mintBatch(accounts[1], mintBatch, minBatchSetOf10, '', {"from": accounts[0]})

    with brownie.reverts():
        # mint with non-owner
        NFT_contract.mintBatch(accounts[1], mintBatch, minBatchSetOf10, '', {"from": accounts[2]})

    with brownie.reverts():
        # mint to zero addres
        NFT_contract.mintBatch(ZERO_ADDRESS, mintBatch, minBatchSetOf10, '', {"from": accounts[0]})

    with brownie.reverts():
        # ids dont match accounts
        NFT_contract.mintBatch(accounts[1], [1,2,3], [1,1], '', {"from": accounts[0]})

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
    # tx1 = NFT_contract.supportsInterface(ERC165_INTERFACE_ID) 
    # returnValue1 =  tx1.return_value
    # assert returnValue1 == True

    assert NFT_contract.supportsInterface(ERC1155_INTERFACE_ID) 
        
    assert NFT_contract.supportsInterface(ERC1155_INTERFACE_ID_METADATA) 
    

def test_pause(NFT_contract):
    # check the pause status, pause, check, unpause, check, with owner and non-owner accounts
    # this test will check all the function that should not work when paused.
    assert NFT_contract.paused() == False
    
    # try and pause as non-owner
    with brownie.reverts():
        NFT_contract.pause({"from": accounts[1]})
    
    NFT_contract.pause()
    assert NFT_contract.paused() == True
    
    # try pausing a paused contract
    with brownie.reverts():
        NFT_contract.pause()
    
    # try functions that should not work when paused
    with brownie.reverts():
        NFT_contract.setURI(NEW_CONTRACT_URI)

    # test burn and burnbatch    
    with brownie.reverts():
        NFT_contract.burn(1,1,{"from": accounts[1]})

    with brownie.reverts():
        NFT_contract.burnBatch([1,2],[1,1],{"from": accounts[1]})

    # check mint and mintbatch
    with brownie.reverts():
        NFT_contract.mint(accounts[1], 1, 1, '', {"from": accounts[0]})
    
    with brownie.reverts():
        NFT_contract.mintBatch(accounts[1], mintBatch, minBatchSetOf10, '', {"from": accounts[0]})


    # check safetransferfrom and safebatchtransferfrom
    with brownie.reverts():
        NFT_contract.safeTransferFrom(accounts[1], accounts[2], 1, 1, '', {"from": accounts[1]})

    with brownie.reverts():
        NFT_contract.safeBatchTransferFrom(accounts[1], accounts[2], [1,2,3], [1,1,1], '', {"from": accounts[1]})

    # check ownership functions
    with brownie.reverts():
        NFT_contract.transferOwnership(accounts[1])

    with brownie.reverts():
        NFT_contract.renounceOwnership()

    # check approval functions
    with brownie.reverts():
        NFT_contract.setApprovalForAll(accounts[0],accounts[5],True)
    
    with brownie.reverts():
        NFT_contract.isApprovedForAll(accounts[0],accounts[5])

    # try and unpause as non-owner
    with brownie.reverts():
        NFT_contract.unpause({"from": accounts[1]})

    NFT_contract.unpause()
    assert NFT_contract.paused() == False

    # try un pausing an unpaused contract
    with brownie.reverts():
        NFT_contract.unpause()


def test_URI(NFT_contract, accounts):
    # change contract URI and restore.
    assert NFT_contract.uri() == CONTRACT_URI
    NFT_contract.setURI(NEW_CONTRACT_URI)
    assert NFT_contract.uri() == NEW_CONTRACT_URI
    assert NFT_contract.uri() != CONTRACT_URI
    NFT_contract.setURI(CONTRACT_URI)
    assert NFT_contract.uri() != NEW_CONTRACT_URI
    assert NFT_contract.uri() == CONTRACT_URI

    with brownie.reverts():
        NFT_contract.setURI(CONTRACT_URI)

def test_mint_single_balanceOf(NFT_contract, accounts, test_mint):
    # Use the test_mint fixture to mint the tokens. 
    # this test checks the balances of this test
    assert NFT_contract.balanceOf(accounts[1],1) == 1
    assert NFT_contract.balanceOf(accounts[1],2) == 1
    assert NFT_contract.balanceOf(accounts[1],3) == 1
    
    # assert_tx_failed  
    with brownie.reverts():
        assert NFT_contract.balanceOf(ZERO_ADDRESS,3) == 1

def test_mint_batch_balanceOf(NFT_contract, accounts, test_mint_batch):
    # Use the test_mint_batch fixture to mint the tokens. 
    # this test checks the balances of this test
    assert NFT_contract.balanceOf(accounts[1],1) == 1
    assert NFT_contract.balanceOf(accounts[1],2) == 1
    assert NFT_contract.balanceOf(accounts[1],3) == 1

def test_safeTransferFrom_balanceOf_single(NFT_contract, accounts, test_mint):
    # transfer NFT 1 from account 1 to account 2 use test_mint_single fixture

    assert NFT_contract.balanceOf(accounts[1],1, {"from": accounts[1]}) == 1
    
    with brownie.reverts():
        # try to transfer item from non item owner account
        NFT_contract.safeTransferFrom(accounts[1], accounts[2], 1, 1, '', {"from": accounts[2]})

    with brownie.reverts():
        # try to transfer item to zero address
        NFT_contract.safeTransferFrom(accounts[1], ZERO_ADDRESS, 1, 1, '', {"from": accounts[1]})

    with brownie.reverts():
        # try to transfer item to self
        NFT_contract.safeTransferFrom(accounts[1], accounts[1], 1, 1, '', {"from": accounts[1]})
    
    with brownie.reverts():
        # try to transfer more items than we own
        NFT_contract.safeTransferFrom(accounts[1], accounts[2], 1, 500, '', {"from": accounts[1]})

    with brownie.reverts():
        # try to transfer nonexisting item
        NFT_contract.safeTransferFrom(accounts[1], accounts[2], 500, 1, '', {"from": accounts[1]})

    NFT_contract.safeTransferFrom(accounts[1], accounts[2], 1, 1, '', {"from": accounts[1]})
    
    assert NFT_contract.balanceOf(accounts[2],1, {"from": accounts[0]}) == 1
    
    with brownie.reverts():
        # try to transfer item again. to trigger zero balance
        NFT_contract.safeTransferFrom(accounts[1], accounts[2], 1, 1, '', {"from": accounts[1]})

    assert NFT_contract.balanceOf(accounts[1],1, {"from": accounts[0]}) == 0
    

# TODO: mint 20 NFTs [1:20] and check the balance for each
def test_mintBatch_balanceOf(NFT_contract, accounts, test_mint_batch):
    # Use the mint three fixture to mint the tokens. 
    # this test checks the balances of this test
    for i in range (1,10):
        assert NFT_contract.balanceOf(accounts[1], i, {"from": accounts[1]}) == 1
        
        with brownie.reverts():
            assert NFT_contract.balanceOf(ZERO_ADDRESS, i, {"from": accounts[1]}) == 1
    
def test_safeBatchTransferFrom_balanceOf_batch(NFT_contract, accounts, test_mint_batch):
    # transfer NFT 1 from account 1 to account 2 use test_mint_single fixture

    NFT_contract.balanceOf(accounts[1],1, {"from": accounts[1]}) == 1
    

    with brownie.reverts():
        # try to transfer item from non item owner account
        NFT_contract.safeBatchTransferFrom(accounts[1], accounts[2], [1,2,3], [1,1,1], '', {"from": accounts[2]})

    with brownie.reverts():
        # try to transfer item to zero address
        NFT_contract.safeBatchTransferFrom(accounts[1], ZERO_ADDRESS, [1,2,3], [1,1,1], '', {"from": accounts[1]})

    with brownie.reverts():
        # try to transfer item to self
        NFT_contract.safeBatchTransferFrom(accounts[1], accounts[1], [1,2,3], [1,1,1], '', {"from": accounts[1]})
    
    with brownie.reverts():
        # try to transfer more items than we own
        NFT_contract.safeBatchTransferFrom(accounts[1], accounts[2], [1,2,3], [1,125,1], '', {"from": accounts[1]})

    with brownie.reverts():
        # mismatched item and amounts
        NFT_contract.safeBatchTransferFrom(accounts[1], accounts[2], [1,2,3], [1,1], '', {"from": accounts[1]})


    with brownie.reverts():
        # try to transfer nonexisting item
        NFT_contract.safeBatchTransferFrom(accounts[1], accounts[2], [1,2,500], [1,1,1], '', {"from": accounts[1]})

    NFT_contract.safeBatchTransferFrom(accounts[1], accounts[2], [1,2,3], [1,1,1], '', {"from": accounts[1]})
    
    with brownie.reverts():
        # try to transfer again, our balances are zero now, should fail
        NFT_contract.safeBatchTransferFrom(accounts[1], accounts[2], [1,2,3], [1,1,1], '', {"from": accounts[1]})


    with brownie.reverts():
        assert NFT_contract.balanceOfBatch([accounts[2],accounts[2],accounts[2]],[1,2], {"from": accounts[0]}) == [1,1,1]
        
    assert NFT_contract.balanceOfBatch([accounts[2],accounts[2],accounts[2]],[1,2,3], {"from": accounts[0]}) == [1,1,1]
    assert NFT_contract.balanceOf(accounts[1],1, {"from": accounts[0]}) == 0

def test_mint_one_burn_one(NFT_contract, accounts, test_mint):
    # check the balance
    assert NFT_contract.balanceOf(accounts[1],1, {"from": accounts[1]}) == 1

    with brownie.reverts():
        # try and burn an item we don't control
        NFT_contract.burn(1,1,{"from": accounts[3]})

    with brownie.reverts():
        # burn an item that contains something we don't own
        NFT_contract.burn(595,1,{"from": accounts[1]})

    with brownie.reverts():
        # burn ah item passing a higher amount than we own
        NFT_contract.burn(1,500,{"from": accounts[1]})

    NFT_contract.burn(1,1,{"from": accounts[1]})

    assert NFT_contract.balanceOf(accounts[1],1, {"from": accounts[1]}) == 0


def test_mint_batch_burn_batch(NFT_contract, accounts, test_mint_batch):
    # check the balance
    assert NFT_contract.balanceOfBatch([accounts[1],accounts[1],accounts[1]],[1,2,3], {"from": accounts[1]}) == [1,1,1]

    with brownie.reverts():
        # try and burn a batch we don't control
        NFT_contract.burnBatch([1,2],[1,1],{"from": accounts[3]})

    with brownie.reverts():
        # ids and amounts array length not matching
        NFT_contract.burnBatch([1,2,3],[1,1],{"from": accounts[1]})

    with brownie.reverts():
        # burn a batch that contains something we don't own
        NFT_contract.burnBatch([2,3,595],[1,1,1],{"from": accounts[1]})

    with brownie.reverts():
        # burn a batch passing a higher amount than we own
        NFT_contract.burnBatch([1,2,3],[1,500,1],{"from": accounts[1]})

    # burn existing
    NFT_contract.burnBatch([1,2],[1,1],{"from": accounts[1]})

    assert NFT_contract.balanceOfBatch([accounts[1],accounts[1],accounts[1]],[1,2,3], {"from": accounts[1]}) == [0,0,1]


    # burn again, should revert
    with brownie.reverts():
        NFT_contract.burnBatch([1,2],[1,1],{"from": accounts[1]})

    assert NFT_contract.balanceOfBatch([accounts[1],accounts[1],accounts[1]],[1,2,3], {"from": accounts[1]}) == [0,0,1]


def test_approval_functions(NFT_contract, accounts, test_mint_batch):

    # self-approval by the owner
    with brownie.reverts():
        NFT_contract.setApprovalForAll(accounts[5],accounts[5],True, {"from": accounts[5]})

    # let's approve and operator for somebody else's account
    with brownie.reverts():
        NFT_contract.setApprovalForAll(accounts[0],accounts[5],True, {"from": accounts[3]})

    # set approval correctly
    NFT_contract.setApprovalForAll(accounts[0],accounts[5],True)

    # check approval
    NFT_contract.isApprovedForAll(accounts[0],accounts[5])

    # remove approval
    NFT_contract.setApprovalForAll(accounts[0],accounts[5],False)


def test_max_batch_size_violation(NFT_contract, accounts):
    TOTAL_BAD_BATCH = 200
    ids = []
    amounts = []
    for i in range(1,TOTAL_BAD_BATCH):
        ids.append(i)
        amounts.append(1)
    with brownie.reverts():
        NFT_contract.mintBatch(accounts[1], ids, amounts, '', {"from": accounts[0]})
    


# Transferring back and forth


def test_ownership_functions(NFT_contract):
    # change owner from account 0 to account 1 and back
    # check all changes by calling isOwner and owner functions
    tx1 = NFT_contract.isOwner()
    returnValue1 =  tx1.return_value
    assert returnValue1 == True
    assert NFT_contract.owner() == accounts[0]

    tx2 = NFT_contract.isOwner({'from': accounts[1]})
    returnValue2 =  tx2.return_value
    assert returnValue2 == False

    with brownie.reverts():
        # try to transfer ownership from non-owner account
        NFT_contract.transferOwnership(accounts[1], {"from": accounts[2]})    
    
    with brownie.reverts():
        # try to transfer ownership to current owner
        NFT_contract.transferOwnership(accounts[0])    
    
    with brownie.reverts():
        # try to transfer ownership to current owner
        NFT_contract.transferOwnership(ZERO_ADDRESS)    
    
    NFT_contract.transferOwnership(accounts[1])
    
    tx1 = NFT_contract.isOwner()
    returnValue1 =  tx1.return_value
    assert returnValue1 == False

    tx2 = NFT_contract.isOwner({'from': accounts[1]})
    returnValue2 =  tx2.return_value
    assert returnValue2 == True
    assert NFT_contract.owner() == accounts[1]

    NFT_contract.transferOwnership(accounts[0],{'from': accounts[1]})
    
    tx1 = NFT_contract.isOwner()
    returnValue1 =  tx1.return_value
    assert returnValue1 == True
    assert NFT_contract.owner() == accounts[0]

    tx2 = NFT_contract.isOwner({'from': accounts[1]})
    returnValue2 =  tx2.return_value
    assert returnValue2 == False

def test_renounce_ownership(NFT_contract):
    tx1 = NFT_contract.isOwner()
    returnValue1 =  tx1.return_value
    assert returnValue1 == True
    assert NFT_contract.owner() == accounts[0]

    with brownie.reverts():
        # try to transfer ownership from non-owner account
        NFT_contract.renounceOwnership({"from": accounts[2]})    

    NFT_contract.renounceOwnership()

    tx1 = NFT_contract.isOwner()
    returnValue1 =  tx1.return_value
    assert returnValue1 == False
    assert NFT_contract.owner() == ZERO_ADDRESS
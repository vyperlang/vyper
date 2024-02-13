import pytest

MAX_BIDS = 128

BIDDING_TIME = 150
REVEAL_TIME = 50
TEST_INCREMENT = 1


@pytest.fixture
def auction_contract(w3, get_contract):
    with open("examples/auctions/blind_auction.vy") as f:
        contract_code = f.read()
        contract = get_contract(contract_code, *[w3.eth.accounts[0], BIDDING_TIME, REVEAL_TIME])
    return contract


def test_initial_state(w3, tester, auction_contract):
    # Check beneficiary is correct
    assert auction_contract.beneficiary() == w3.eth.accounts[0]
    # Check that bidding end time is correct
    assert (
        auction_contract.biddingEnd()
        == tester.get_block_by_number("latest")["timestamp"] + BIDDING_TIME
    )  # noqa: E501
    # Check that the reveal end time is correct
    assert auction_contract.revealEnd() == auction_contract.biddingEnd() + REVEAL_TIME
    # Check auction has not ended
    assert auction_contract.ended() is False
    # Check highest bid is 0
    assert auction_contract.highestBid() == 0
    # Check highest bidder is empty
    assert auction_contract.highestBidder() is None


def test_late_bid(w3, auction_contract, tx_failed):
    k1 = w3.eth.accounts[1]

    # Move time forward past bidding end
    w3.testing.mine(BIDDING_TIME + TEST_INCREMENT)

    # Try to bid after bidding has ended
    with tx_failed():
        auction_contract.bid(
            w3.keccak(
                b"".join(
                    [
                        (200).to_bytes(32, byteorder="big"),
                        (0).to_bytes(32, byteorder="big"),
                        (8675309).to_bytes(32, byteorder="big"),
                    ]
                )
            ),
            transact={"value": 200, "from": k1},
        )


def test_too_many_bids(w3, auction_contract, tx_failed):
    k1 = w3.eth.accounts[1]

    # First 128 bids should be able to be placed successfully
    for i in range(MAX_BIDS):
        auction_contract.bid(
            w3.keccak(
                b"".join(
                    [
                        (i).to_bytes(32, byteorder="big"),
                        (1).to_bytes(32, byteorder="big"),
                        (8675309).to_bytes(32, byteorder="big"),
                    ]
                )
            ),
            transact={"value": i, "from": k1},
        )

    # 129th bid should fail
    with tx_failed():
        auction_contract.bid(
            w3.keccak(
                b"".join(
                    [
                        (128).to_bytes(32, byteorder="big"),
                        (0).to_bytes(32, byteorder="big"),
                        (8675309).to_bytes(32, byteorder="big"),
                    ]
                )
            ),
            transact={"value": 128, "from": k1},
        )


def test_early_reval(w3, auction_contract, tx_failed):
    k1 = w3.eth.accounts[1]

    # k1 places 1 real bid
    auction_contract.bid(
        w3.keccak(
            b"".join(
                [
                    (100).to_bytes(32, byteorder="big"),
                    (0).to_bytes(32, byteorder="big"),
                    (8675309).to_bytes(32, byteorder="big"),
                ]
            )
        ),
        transact={"value": 100, "from": k1},
    )

    # Move time slightly forward (still before bidding has ended)
    w3.testing.mine(TEST_INCREMENT)

    # Try to reveal early
    _values = [0] * MAX_BIDS  # Initialized with 128 default values
    _fakes = [False] * MAX_BIDS  # Initialized with 128 default values
    _secrets = [b"\x00" * 32] * MAX_BIDS  # Initialized with 128 default values
    _numBids = 1
    _values[0] = 100
    _fakes[0] = False
    _secrets[0] = (8675309).to_bytes(32, byteorder="big")
    with tx_failed():
        auction_contract.reveal(
            _numBids, _values, _fakes, _secrets, transact={"value": 0, "from": k1}
        )

    # Check highest bidder is still empty
    assert auction_contract.highestBidder() is None
    # Check highest bid is still 0
    assert auction_contract.highestBid() == 0


def test_late_reveal(w3, auction_contract, tx_failed):
    k1 = w3.eth.accounts[1]

    # k1 places 1 real bid
    auction_contract.bid(
        w3.keccak(
            b"".join(
                [
                    (100).to_bytes(32, byteorder="big"),
                    (0).to_bytes(32, byteorder="big"),
                    (8675309).to_bytes(32, byteorder="big"),
                ]
            )
        ),
        transact={"value": 100, "from": k1},
    )

    # Move time forward past bidding _and_ reveal time
    w3.testing.mine(BIDDING_TIME + REVEAL_TIME + TEST_INCREMENT)

    # Try to reveal late
    _values = [0] * MAX_BIDS  # Initialized with 128 default values
    _fakes = [False] * MAX_BIDS  # Initialized with 128 default values
    _secrets = [b"\x00" * 32] * MAX_BIDS  # Initialized with 128 default values
    _numBids = 1
    _values[0] = 100
    _fakes[0] = False
    _secrets[0] = (8675309).to_bytes(32, byteorder="big")
    with tx_failed():
        auction_contract.reveal(
            _numBids, _values, _fakes, _secrets, transact={"value": 0, "from": k1}
        )

    # Check highest bidder is still empty
    assert auction_contract.highestBidder() is None
    # Check highest bid is still 0
    assert auction_contract.highestBid() == 0


def test_early_end(w3, auction_contract, tx_failed):
    k0 = w3.eth.accounts[0]

    # Should not be able to end auction before reveal time has ended
    with tx_failed():
        auction_contract.auctionEnd(transact={"value": 0, "from": k0})


def test_double_end(w3, auction_contract, tx_failed):
    k0 = w3.eth.accounts[0]

    # Move time forward past bidding and reveal end
    w3.testing.mine(BIDDING_TIME + REVEAL_TIME + TEST_INCREMENT)

    # First auction end should succeed
    auction_contract.auctionEnd(transact={"value": 0, "from": k0})

    # Should not be able to end auction twice
    with tx_failed():
        auction_contract.auctionEnd(transact={"value": 0, "from": k0})


def test_blind_auction(w3, auction_contract):
    k0, k1, k2, k3 = w3.eth.accounts[0:4]

    ###################################################################
    #                         Place bids                              #
    ###################################################################

    # k1 places 1 real bid
    auction_contract.bid(
        w3.keccak(
            b"".join(
                [
                    (100).to_bytes(32, byteorder="big"),
                    (0).to_bytes(32, byteorder="big"),
                    (8675309).to_bytes(32, byteorder="big"),
                ]
            )
        ),
        transact={"value": 100, "from": k1},
    )

    # k2 places 1 real bid (highest) and 2 fake
    auction_contract.bid(
        w3.keccak(
            b"".join(
                [
                    (150).to_bytes(32, byteorder="big"),
                    (1).to_bytes(32, byteorder="big"),
                    (1234567).to_bytes(32, byteorder="big"),
                ]
            )
        ),
        transact={"value": 150, "from": k2},
    )
    auction_contract.bid(
        w3.keccak(
            b"".join(
                [
                    (200).to_bytes(32, byteorder="big"),
                    (0).to_bytes(32, byteorder="big"),
                    (1234567).to_bytes(32, byteorder="big"),
                ]
            )
        ),
        transact={"value": 250, "from": k2},
    )
    auction_contract.bid(
        w3.keccak(
            b"".join(
                [
                    (300).to_bytes(32, byteorder="big"),
                    (1).to_bytes(32, byteorder="big"),
                    (1234567).to_bytes(32, byteorder="big"),
                ]
            )
        ),
        transact={"value": 300, "from": k2},
    )

    # k3 places 2 fake bids
    auction_contract.bid(
        w3.keccak(
            b"".join(
                [
                    (175).to_bytes(32, byteorder="big"),
                    (1).to_bytes(32, byteorder="big"),
                    (9876543).to_bytes(32, byteorder="big"),
                ]
            )
        ),
        transact={"value": 175, "from": k3},
    )
    auction_contract.bid(
        w3.keccak(
            b"".join(
                [
                    (275).to_bytes(32, byteorder="big"),
                    (1).to_bytes(32, byteorder="big"),
                    (9876543).to_bytes(32, byteorder="big"),
                ]
            )
        ),
        transact={"value": 275, "from": k3},
    )

    ###################################################################
    #                          Reveal bids.                           #
    ###################################################################

    # Move time forward past bidding end (still within reveal end)
    w3.testing.mine(BIDDING_TIME + TEST_INCREMENT)

    # Reveal k1 bids
    _values = [0] * MAX_BIDS  # Initialized with 128 default values
    _fakes = [False] * MAX_BIDS  # Initialized with 128 default values
    _secrets = [b"\x00" * 32] * MAX_BIDS  # Initialized with 128 default values
    _numBids = 1
    _values[0] = 100
    _fakes[0] = False
    _secrets[0] = (8675309).to_bytes(32, byteorder="big")
    auction_contract.reveal(_numBids, _values, _fakes, _secrets, transact={"value": 0, "from": k1})

    #: Check that highest bidder and highest bid have updated
    assert auction_contract.highestBid() == 100
    assert auction_contract.highestBidder() == k1

    # Reveal k2 bids
    _values = [0] * MAX_BIDS  # Initialized with 128 default values
    _fakes = [False] * MAX_BIDS  # Initialized with 128 default values
    _secrets = [b"\x00" * 32] * MAX_BIDS  # Initialized with 128 default values
    _values[0] = 150
    _fakes[0] = True
    _secrets[0] = (1234567).to_bytes(32, byteorder="big")
    _values[1] = 200
    _fakes[1] = False
    _secrets[1] = (1234567).to_bytes(32, byteorder="big")
    _values[2] = 300
    _fakes[2] = True
    _secrets[2] = (1234567).to_bytes(32, byteorder="big")
    balance_before_reveal = w3.eth.get_balance(k2)
    auction_contract.reveal(3, _values, _fakes, _secrets, transact={"value": 0, "from": k2})
    balance_after_reveal = w3.eth.get_balance(k2)

    #: Check that highest bidder and highest bid have updated
    assert auction_contract.highestBid() == 200
    assert auction_contract.highestBidder() == k2

    # Check for refund from false bids (300 + 150) and partial deposit (50)
    assert balance_after_reveal == (balance_before_reveal + 500)

    # Reveal k3 bids
    _values = [0] * MAX_BIDS  # Initialized with 128 default values
    _fakes = [False] * MAX_BIDS  # Initialized with 128 default values
    _secrets = [b"\x00" * 32] * MAX_BIDS  # Initialized with 128 default values
    _values[0] = 175
    _fakes[0] = True
    _secrets[0] = (9876543).to_bytes(32, byteorder="big")
    _values[1] = 275
    _fakes[1] = True
    _secrets[1] = (9876543).to_bytes(32, byteorder="big")
    balance_before_reveal = w3.eth.get_balance(k3)
    auction_contract.reveal(2, _values, _fakes, _secrets, transact={"value": 0, "from": k3})
    balance_after_reveal = w3.eth.get_balance(k3)

    #: Check that highest bidder and highest bid have NOT updated
    assert auction_contract.highestBidder() == k2
    assert auction_contract.highestBid() == 200

    # Check for refund from false bids (175 + 275 = 450)
    assert balance_after_reveal == (balance_before_reveal + 450)

    ###################################################################
    #                          End auction.                           #
    ###################################################################

    # Move time forward past bidding and reveal end
    w3.testing.mine(REVEAL_TIME)

    # End the auction
    balance_before_end = w3.eth.get_balance(k0)
    auction_contract.auctionEnd(transact={"value": 0, "from": k0})
    balance_after_end = w3.eth.get_balance(k0)

    # Check that auction indeed ended
    assert auction_contract.ended() is True

    # Check that beneficiary has been paid
    assert balance_after_end == (balance_before_end + 200)

    # Check that k1 is able to withdraw their outbid bid
    balance_before_withdraw = w3.eth.get_balance(k1)
    auction_contract.withdraw(transact={"value": 0, "from": k1})
    balance_after_withdraw = w3.eth.get_balance(k1)
    assert balance_after_withdraw == (balance_before_withdraw + 100)

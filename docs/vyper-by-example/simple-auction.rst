.. index:: auction;open, open auction

Simple Open Auction
*******************

.. _simple_auction:

.. warning::

   This is example code for learning purposes. Do not use in production without thorough review and testing.

As an introductory example of a smart contract written in Vyper, we will begin
with a simple open auction contract. As we dive into the code,
it is important to note that Vyper uses Python-like syntax, making it familiar
to Python developers, but it is a distinct language with its own type system,
decorators (like ``@deploy``, ``@external``), and keywords.

In this contract, we will be looking at a simple open auction contract where
participants can submit bids during a limited time period. When the auction
period ends, a predetermined beneficiary will receive the amount of the highest
bid.

.. literalinclude:: ../../examples/auctions/simple_open_auction.vy
  :language: vyper
  :linenos:

As you can see, this example only has a constructor, three methods to call, and
a few variables to manage the contract state. Believe it or not, this is all we
need for a basic implementation of an auction smart contract.

Let's get started!

.. literalinclude:: ../../examples/auctions/simple_open_auction.vy
  :language: vyper
  :lineno-start: 3
  :lines: 3-19

We begin by declaring a few variables to keep track of our contract state.
We initialize a global variable ``beneficiary`` by calling ``public`` on the
datatype ``address``. The ``beneficiary`` will be the receiver of money from
the highest bidder.  We also initialize the variables ``auctionStart`` and
``auctionEnd`` with the datatype ``uint256`` to manage the open auction
period and ``highestBid`` with datatype ``uint256`` to manage the highest bid amount in wei. The variable ``ended`` is a
boolean to determine whether the auction is officially over. The variable ``pendingReturns`` is a ``HashMap`` which
enables the use of key-value pairs to keep proper track of the auction's withdrawal pattern.

You may notice all of the variables being passed into the ``public``
function. By declaring the variable *public*, the variable is
callable by external contracts. Initializing the variables without the ``public``
function defaults to a private declaration and thus only accessible to methods
within the same contract. The ``public`` function additionally creates a
'getter' function for the variable, accessible through an external call such as
``contract.beneficiary()``.

Now, the constructor.

.. literalinclude:: ../../examples/auctions/simple_open_auction.vy
  :language: vyper
  :lineno-start: 22
  :lines: 22-29

The contract is initialized with three arguments: ``_beneficiary`` of type
``address``, ``_auction_start`` with type ``uint256`` and ``_bidding_time`` with
type ``uint256``, the time difference between the start and end of the auction. We
store the beneficiary and auction start time, then compute ``self.auctionEnd``
by adding ``_bidding_time`` to ``self.auctionStart``.
Notice that we have access to the current time by calling ``block.timestamp``.
``block`` is an object available within any Vyper contract and provides information
about the block at the time of calling. Similar to ``block``, another important object
available to us within the contract is ``msg``, which provides information on the method
caller as we will soon see.

With initial setup out of the way, let's look at how our users can make bids.

.. literalinclude:: ../../examples/auctions/simple_open_auction.vy
  :language: vyper
  :lineno-start: 31
  :lines: 31-48

The ``@payable`` decorator will allow a user to send some ether to the
contract in order to call the decorated method. In this case, a user wanting
to make a bid would call the ``bid()`` method while sending an amount equal
to their desired bid (not including gas fees). When calling any method within a
contract, we are provided with a built-in variable ``msg`` and we can access
the public address of any method caller with ``msg.sender``. Similarly, the
amount of ether a user sends can be accessed by calling ``msg.value``.

Here, we first check whether the current time is within the bidding period by
comparing with the auction's start and end times using the ``assert`` function
which takes any boolean statement. We also check to see if the new bid is greater
than the highest bid. If all three ``assert`` statements pass, we can safely continue
to the next lines; otherwise, the ``bid()`` method will throw an error and revert the
transaction. We then record the previous highest bid in the ``pendingReturns`` mapping
(following the withdrawal pattern for security), and update ``highestBid`` and
``highestBidder`` to reflect the new winning bid.

.. literalinclude:: ../../examples/auctions/simple_open_auction.vy
  :language: vyper
  :lineno-start: 50
  :lines: 50-58

The ``withdraw()`` method allows previously outbid participants to withdraw
their funds. Rather than sending refunds directly during ``bid()`` (which
would allow a malicious contract to block new bids), we use the `withdrawal
pattern <https://docs.soliditylang.org/en/latest/common-patterns.html#withdrawal-from-contracts>`_:
each bidder pulls their own refund. The method reads the pending amount,
zeroes it out (to prevent re-entrancy), and sends the funds.

.. literalinclude:: ../../examples/auctions/simple_open_auction.vy
  :language: vyper
  :lineno-start: 60
  :lines: 60-87

With the ``endAuction()`` method, we check whether our current time is past
the ``auctionEnd`` time we set upon initialization of the contract. We also
check that ``self.ended`` had not previously been set to True. We do this
to prevent any calls to the method if the auction had already ended,
which could potentially be malicious if the check had not been made.
We then officially end the auction by setting ``self.ended`` to ``True``
and sending the highest bid amount to the beneficiary.

And there you have it - an open auction contract. Of course, this is a
simplified example with barebones functionality and can be improved.
Hopefully, this has provided some insight into the possibilities of Vyper.
As we move on to exploring more complex examples, we will encounter more
design patterns and features of the Vyper language.

###################
Vyper by Example
###################

.. index:: auction;open, open auction

*******************
Simple Open Auction
*******************

.. _simple_auction:

As an introductory example of a smart contract written in Vyper, we will begin
with a simple open auction contract. As we dive into the code,
it is important to remember that all Vyper syntax is valid Python3 syntax,
however not all Python3 functionality is available in Vyper.

In this contract, we will be looking at a simple open auction contract where
participants can submit bids during a limited time period. When the auction
period ends, a predetermined beneficiary will receive the amount of the highest
bid.

.. literalinclude:: ../examples/auctions/simple_open_auction.vy
  :language: python
  :linenos:

As you can see, this example only has a constructor, two methods to call, and
a few variables to manage the contract state. Believe it or not, this is all we
need for a basic implementation of an auction smart contract.

Let's get started!

.. literalinclude:: ../examples/auctions/simple_open_auction.vy
  :language: python
  :lines: 3-14

We begin by declaring a few variables to keep track of our contract state.
We initialize a global variable ``beneficiary`` by calling ``public`` on the
datatype ``address``. The ``beneficiary`` will be the receiver of money from
the highest bidder.  We also initialize the variables ``auction_start`` and
``auction_end`` with the datatype ``timestamp`` to manage the open auction
period and ``highest_bid`` with datatype ``wei_value``, the smallest
denomination of ether, to manage auction state. The variable ``ended`` is a
boolean to determine whether the auction is officially over.

You may notice all of the variables being passed into the ``public``
function. By declaring the variable *public*, the variable is
callable by external contracts. Initializing the variables without the  ``public``
function defaults to a private declaration and thus only accessible to methods
within the same contract. The ``public`` function additionally creates a
‘getter’ function for the variable, accessible with a call such as
``self.get_beneficiary(some_address)``.

Now, the constructor.

.. literalinclude:: ../examples/auctions/simple_open_auction.vy
  :language: python
  :pyobject: __init__

The contract is initialized with two arguments: ``_beneficiary`` of type
``address`` and ``_bidding_time`` with type ``timedelta``, the time difference
between the start and end of the auction. We then store these two pieces of
information into the contract variables ``self.beneficiary`` and
``self.auction_end``. Notice that we have access to the current time by
calling ``block.timestamp``. ``block`` is an object available within any Vyper
contract and provides information about the block at the time of calling.
Similar to ``block``, another important object available to us within the
contract is ``msg``, which provides information on the method caller as we will
soon see.

With initial setup out of the way, lets look at how our users can make bids.

.. literalinclude:: ../examples/auctions/simple_open_auction.vy
  :language: python
  :pyobject: bid

The ``@payable`` decorator will allow a user to send some ether to the
contract in order to call the decorated method. In this case, a user wanting
to make a bid would call the ``bid()`` method while sending an amount equal
to their desired bid (not including gas fees). When calling any method within a
contract, we are provided with a built-in variable ``msg`` and we can access
the public address of any method caller with ``msg.sender``. Similarly, the
amount of ether a user sends can be accessed by calling ``msg.value``.

.. warning:: ``msg.sender`` will change between internal function calls so that
  if you're calling a function from the outside, it's correct for the first
  function call. But then, for the function calls after, ``msg.sender`` will
  reference the contract itself as opposed to the sender of the transaction.

Here, we first check whether the current time is before the auction's end time
using the ``assert`` function which takes any boolean statement. We also check
to see if the new bid is greater than the highest bid. If the two ``assert``
statements pass, we can safely continue to the next lines; otherwise, the
``bid()`` method will throw an error and revert the transaction. If the two
``assert`` statements and the check that the previous bid is not equal to zero pass,
we can safely conclude that we have a valid new highest bid. We will send back
the previous ``highest_bid`` to the previous ``highest_bidder`` and set our new
``highest_bid`` and ``highest_bidder``.

.. literalinclude:: ../examples/auctions/simple_open_auction.vy
  :language: python
  :pyobject: end_auction

With the ``auction_end()`` method, we check whether our current time is past
the ``auction_end`` time we set upon initialization of the contract. We also
check that ``self.ended`` had not previously been set to True. We do this
to prevent any calls to the method if the auction had already ended,
which could potentially be malicious if the check had not been made.
We then officially end the auction by setting ``self.ended`` to ``True``
and sending the highest bid amount to the beneficiary.

And there you have it - an open auction contract. Of course, this is a
simplified example with barebones functionality and can be improved.
Hopefully, this has provided some insight to the possibilities of Vyper.
As we move on to exploring more complex examples, we will encounter more
design patterns and features of the Vyper language.


And of course, no smart contract tutorial is complete without a note on
security.

.. note::
  It's always important to keep security in mind when designing a smart
  contract. As any application becomes more complex, the greater the potential for
  introducing new risks. Thus, it's always good practice to keep contracts as
  readable and simple as possible.

Whenever you're ready, let's turn it up a notch in the next example.


.. index:: purchases

*********************
Safe Remote Purchases
*********************

.. _safe_remote_purchases:


In this example, we have an escrow contract implementing a system for a trustless
transaction between a buyer and a seller. In this system, a seller posts an item
for sale and makes a deposit to the contract of twice the item's ``value``. At
this moment, the contract has a balance of 2 * ``value``. The seller can reclaim
the deposit and close the sale as long as a buyer has not yet made a purchase.
If a buyer is interested in making a purchase, they would make a payment and
submit an equal amount for deposit (totaling 2 * ``value``) into the contract
and locking the contract from further modification. At this moment, the contract
has a balance of 4 * ``value`` and the seller would send the item to buyer. Upon
the buyer's receipt of the item, the buyer will mark the item as received in the
contract, thereby returning the buyer's deposit (not payment), releasing the
remaining funds to the seller, and completing the transaction.

There are certainly others ways of designing a secure escrow system with less
overhead for both the buyer and seller, but for the purpose of this example,
we want to explore one way how an escrow system can be implemented trustlessly.

Let's go!

.. literalinclude:: ../examples/safe_remote_purchase/safe_remote_purchase.vy
  :language: python
  :linenos:

This is also a moderately short contract, however a little more complex in
logic. Let's break down this contract bit by bit.

.. literalinclude:: ../examples/safe_remote_purchase/safe_remote_purchase.vy
  :language: python
  :lines: 16-19

Like the other contracts, we begin by declaring our global variables public with
their respective datatypes. Remember that the ``public`` function allows the
variables to be *readable* by an external caller, but not *writeable*.

.. literalinclude:: ../examples/safe_remote_purchase/safe_remote_purchase.vy
  :language: python
  :pyobject: __init__

With a ``@payable`` decorator on the constructor, the contract creator will be
required to make an initial deposit equal to twice the item's ``value`` to
initialize the contract, which will be later returned. This is in addition to
the gas fees needed to deploy the contract on the blockchain, which is not
returned. We ``assert`` that the deposit is divisible by 2 to ensure that the
seller deposited a valid amount. The constructor stores the item's value
in the contract variable ``self.value`` and saves the contract creator into
``self.seller``. The contract variable ``self.unlocked`` is initialized to
``True``.

.. literalinclude:: ../examples/safe_remote_purchase/safe_remote_purchase.vy
  :language: python
  :pyobject: abort

The ``abort()`` method is a method only callable by the seller and while the
contract is still ``unlocked``—meaning it is callable only prior to any buyer
making a purchase. As we will see in the ``purchase()`` method that when
a buyer calls the ``purchase()`` method and sends a valid amount to the contract,
the contract will be locked and the seller will no longer be able to call
``abort()``.

When the seller calls ``abort()`` and if the ``assert`` statements pass, the
contract will call the ``selfdestruct()`` function and refunds the seller and
subsequently destroys the contract.

.. literalinclude:: ../examples/safe_remote_purchase/safe_remote_purchase.vy
  :language: python
  :pyobject: purchase

Like the constructor, the ``purchase()`` method has a ``@payable`` decorator,
meaning it can be called with a payment. For the buyer to make a valid
purchase, we must first ``assert`` that the contract's ``unlocked`` property is
``True`` and that the amount sent is equal to twice the item's value. We then
set the buyer to the ``msg.sender`` and lock the contract. At this point, the
contract has a balance equal to 4 times the item value and the seller must
send the item to the buyer.

.. literalinclude:: ../examples/safe_remote_purchase/safe_remote_purchase.vy
  :language: python
  :pyobject: received

Finally, upon the buyer's receipt of the item, the buyer can confirm their
receipt by calling the ``received()`` method to distribute the funds as
intended—where the seller receives 3/4 of the contract balance and the buyer
receives 1/4.

By calling ``received()``, we begin by checking that the contract is indeed
locked, ensuring that a buyer had previously paid. We also ensure that this
method is only callable by the buyer. If these two ``assert`` statements pass,
we refund the buyer their initial deposit and send the seller the remaining
funds. The contract is finally destroyed and the transaction is complete.

Whenever we’re ready, let’s move on to the next example.


.. index:: crowdfund

*********
Crowdfund
*********

.. _crowdfund:

Now, let's explore a straightforward example for a crowdfunding contract where
prospective participants can contribute funds to a campaign. If the total
contribution to the campaign reaches or surpasses a predetermined funding goal,
the funds will be sent to the  beneficiary at the end of the campaign deadline.
Participants will be refunded their respective contributions if the total
funding does not reach its target goal.


.. literalinclude:: ../examples/crowdfund.vy
  :language: python
  :linenos:

Most of this code should be relatively straightforward after going through our
previous examples. Let's dive right in.

.. literalinclude:: ../examples/crowdfund.vy
  :language: python
  :lines: 1-8

Like other examples, we begin by initiating our variables - except this time,
we're not calling them with the ``public`` function. Variables initiated this
way are, by default, private.

.. note::
  Unlike the existence of the function ``public()``, there is no equivalent
  ``private()`` function. Variables simply default to private if initiated
  without the ``public()`` function.

The ``funders`` variable is initiated as a mapping where the key is a number,
and the value is a struct representing the contribution of each participant.
This struct contains each participant's public address and their respective
value contributed to the fund. The key corresponding to each struct in the
mapping will be represented by the variable ``nextFunderIndex`` which is
incremented with each additional contributing participant. Variables initialized
with the ``int128`` type without an explicit value, such as ``nextFunderIndex``,
defaults to ``0``. The ``beneficiary`` will be the final receiver of the funds
once the crowdfunding period is over—as determined by the ``deadline`` and
``timelimit`` variables. The ``goal`` variable is the target total contribution
of all participants. ``refundIndex`` is a variable for bookkeeping purposes in
order to avoid gas limit issues in the scenario of a refund.


.. literalinclude:: ../examples/crowdfund.vy
  :language: python
  :pyobject: __init__

Our constructor function takes 3 arguments: the beneficiary's address, the goal
in wei value, and the difference in time from start to finish of the
crowdfunding. We initialize the arguments as contract variables with their
corresponding names. Additionally, a ``self.deadline`` is initialized to set
a definitive end time for the crowdfunding period.

Now lets take a look at how a person can participate in the crowdfund.

.. literalinclude:: ../examples/crowdfund.vy
  :language: python
  :pyobject: participate

Once again, we see the ``@payable`` decorator on a method, which allows a
person to send some ether along with a call to the method. In this case,
the ``participate()`` method accesses the sender's address with ``msg.sender``
and the corresponding amount sent with ``msg.value``. This information is stored
into a struct and then saved into the ``funders`` mapping with
``self.nextFunderIndex`` as the key. As more participants are added to the
mapping, ``self.nextFunderIndex`` increments appropriately to properly index
each participant.

.. literalinclude:: ../examples/crowdfund.vy
  :language: python
  :pyobject: finalize

The ``finalize()`` method is used to complete the crowdfunding process. However,
to complete the crowdfunding, the method first checks to see if the crowdfunding
period is over and that the balance has reached/passed its set goal. If those
two conditions pass, the contract calls the ``selfdestruct()`` function and
sends the collected funds to the beneficiary.

.. note::
  Notice that we have access to the total amount sent to the contract by
  calling ``self.balance``, a variable we never explicitly set. Similar to ``msg``
  and ``block``, ``self.balance`` is a built-in variable thats available in all
  Vyper contracts.

We can finalize the campaign if all goes well, but what happens if the
crowdfunding campaign isn't successful? We're going to need a way to refund
all the participants.

.. literalinclude:: ../examples/crowdfund.vy
  :language: python
  :pyobject: refund

In the ``refund()`` method, we first check that the crowdfunding period is
indeed over and that the total collected balance is less than the ``goal`` with
the  ``assert`` statement . If those two conditions pass, we then loop through
every participant and call ``send()`` to send each participant their respective
contribution. For the sake of gas limits, we group the number of contributors
in batches of 30 and refund them one at a time. Unfortunately, if there's a
large number of of participants, multiple calls to ``refund()`` may be
necessary.

.. index:: voting, ballot

******
Voting
******

In this contract, we will implement a system for participants to vote on a list
of proposals. The chairperson of the contract will be able to give each
participant the right to vote, and each participant may choose to vote, or
delegate their vote to another voter. Finally, a winning proposal will be
determined upon calling the ``winning_proposals()`` method, which iterates through
all the proposals and returns the one with the greatest number of votes.


.. literalinclude:: ../examples/voting/ballot.vy
  :language: python
  :linenos:

As we can see, this is contract of moderate length which we will dissect
section by section. Let’s begin!

.. literalinclude:: ../examples/voting/ballot.vy
  :language: python
  :lines: 3-25

The variable ``voters`` is initialized as a mapping where the key is
the voter’s public address and the value is a struct describing the
voter’s properties: ``weight``, ``voted``, ``delegate``, and ``vote``, along
with their respective datatypes.

Similarly, the ``proposals`` variable is initialized as a ``public`` mapping
with ``int128`` as the key’s datatype and a struct to represent each proposal
with the properties ``name`` and ``vote_count``. Like our last example, we can
access any value by key’ing into the mapping with a number just as one would
with an index in an array.

Then, ``voter_count`` and ``chairperson`` are initialized as ``public`` with
their respective datatypes.

Let’s move onto the constructor.

.. literalinclude:: ../examples/voting/ballot.vy
  :language: python
  :pyobject: __init__

.. warning:: Both ``msg.sender`` and ``msg.balance`` change between internal
  function calls so that if you're calling a function from the outside, it's
  correct for the first function call. But then, for the function calls after,
  ``msg.sender`` and ``msg.balance`` reference the contract itself as opposed
  to the sender of the transaction.

In the constructor, we hard-coded the contract to accept an
array argument of exactly two proposal names of type ``bytes32`` for the contracts
initialization. Because upon initialization, the ``__init__()`` method is called
by the contract creator, we have access to the contract creator’s address with
``msg.sender`` and store it in the contract variable ``self.chairperson``. We
also initialize the contract variable ``self.voter_count`` to zero to initially
represent the number of votes allowed. This value will be incremented as each
participant in the contract is given the right to vote by the method
``give_right_to_vote()``, which we will explore next. We loop through the two
proposals from the argument and insert them into ``proposals`` mapping with
their respective index in the original array as its key.

Now that the initial setup is done, lets take a look at the functionality.

.. literalinclude:: ../examples/voting/ballot.vy
  :language: python
  :pyobject: give_right_to_vote

We need a way to control who has the ability to vote. The method
``give_right_to_vote()`` is a method callable by only the chairperson by taking
a voter address and granting it the right to vote by incrementing the voter's
``weight`` property. We sequentially check for 3 conditions using ``assert``.
The ``assert not`` function will check for falsy boolean values -
in this case, we want to know that the voter has not already voted. To represent
voting power, we will set their ``weight`` to ``1`` and we will keep track of the
total number of voters by incrementing ``voter_count``.

.. literalinclude:: ../examples/voting/ballot.vy
  :language: python
  :pyobject: delegate

In the method ``delegate``, firstly, we check to see that ``msg.sender`` has not
already voted and secondly, that the target delegate and the ``msg.sender`` are
not the same. Voters shouldn’t be able to delegate votes to themselves. We,
then, loop through all the voters to determine whether the person delegate to
had further delegated their vote to someone else in order to follow the
chain of delegation. We then mark the ``msg.sender`` as having voted if they
delegated their vote. We increment the proposal’s ``vote_count`` directly if
the delegate had already voted or increase the  delegate’s vote ``weight``
if the delegate has not yet voted.

.. literalinclude:: ../examples/voting/ballot.vy
  :language: python
  :pyobject: vote

Now, let’s take a look at the logic inside the ``vote()`` method, which is
surprisingly simple. The method takes the key of the proposal in the ``proposals``
mapping as an argument, check that the method caller had not already voted,
sets the voter’s ``vote`` property to the proposal key, and increments the
proposals ``vote_count`` by the voter’s ``weight``.

With all the basic functionality complete, what’s left is simply returning
the winning proposal. To do this, we have two methods: ``winning_proposal()``,
which returns the key of the proposal, and ``winner_name()``, returning the
name of the proposal. Notice the ``@constant`` decorator on these two methods.
We do this because the two methods only read the blockchain state and do not
modify it. Remember, reading the blockchain state is free; modifying the state
costs gas. By having the ``@constant`` decorator, we let the EVM know that this
is a read-only function and we benefit by saving gas fees.

.. literalinclude:: ../examples/voting/ballot.vy
  :language: python
  :pyobject: winning_proposal

The ``winning_proposal()`` method returns the key of proposal in the ``proposals``
mapping. We will keep track of greatest number of votes and the winning
proposal with the variables ``winning_vote_count`` and ``winning_proposal``,
respectively by looping through all the proposals.

.. literalinclude:: ../examples/voting/ballot.vy
  :language: python
  :pyobject: winner_name

And finally, the ``winner_name()`` method returns the name of the proposal by
key’ing into the ``proposals`` mapping with the return result of the
``winning_proposal()`` method.

And there you have it - a voting contract. Currently, many transactions
are needed to assign the rights to vote to all participants. As an exercise,
can we try to optimize this?

Now that we're familiar with basic contracts. Let's step up the difficulty.

.. index:: stock;company, company stock

*************
Company Stock
*************

.. _company_stock:

This contract is just a tad bit more thorough than the ones we've previously
encountered. In this example, we are going to look at a comprehensive contract
that manages the holdings of all shares of a company. The contract allows for
a person to buy, sell, and transfer shares of a company as well as allowing for
the company to pay a person in ether. The company, upon initialization of the
contract, holds all shares of the company at first but can sell them all.

Let's get started.

.. literalinclude:: ../examples/stock/company.vy
  :language: python
  :linenos:

The contract contains a number of methods that modify the contract state as
well as a few 'getter' methods to read it. We first declare several events 
that the contract logs. We then declare our global variables, followed by
function defintions.

.. literalinclude:: ../examples/stock/company.vy
  :language: python
  :lines: 7-13

We initiate the ``company`` variable to be of type ``address`` that's public.
The ``total_shares`` variable is of type ``currency_value``, which in this case
represents the total available shares of the company. The ``price`` variable
represents the wei value of a share and ``holdings`` is a mapping that maps an
address to the number of shares the address owns.

.. literalinclude:: ../examples/stock/company.vy
  :language: python
  :pyobject: __init__

In the constructor, we set up the contract to check for valid inputs during
the initialization of the contract via the two ``assert`` statements. If the
inputs are valid, the contract variables are set accordingly and the
company's address is initialized to hold all shares of the company in the
``holdings`` mapping.

.. literalinclude:: ../examples/stock/company.vy
  :language: python
  :pyobject: stock_available

We will be seeing a few ``@constant`` decorators in this contract—which is
used to decorate methods that simply read the contract state or return a simple
calculation on the contract state without modifying it. Remember, reading the
blockchain is free, writing on it is not. Since Vyper is a statically typed
language, we see an arrow following the definition of the ``stock_available()``
method, which simply represents the data type which the function is expected
to return. In the method, we simply key into ``self.holdings`` with the
company's address and check it's holdings.

Now, lets take a look at a method that lets a person buy stock from the
company's holding.

.. literalinclude:: ../examples/stock/company.vy
  :language: python
  :pyobject: buy_stock

The ``buy_stock()`` method is a ``@payable`` method which takes an amount of
ether sent and calculates the ``buy_order`` (the stock value equivalence at
the time of call). The number of shares is deducted from the company's holdings
and transferred to the sender's in the ``holdings`` mapping.

Now that people can buy shares, how do we check someone's holdings?

.. literalinclude:: ../examples/stock/company.vy
  :language: python
  :pyobject: get_holdings

The ``get_holdings()`` is another ``@constant`` method that takes an ``address``
and returns its corresponding stock holdings by keying into ``self.holdings``.

.. literalinclude:: ../examples/stock/company.vy
  :language: python
  :pyobject: cash

To check the ether balance of the company, we can simply call the getter method
``cash()``.

.. literalinclude:: ../examples/stock/company.vy
  :language: python
  :pyobject: sell_stock

To sell a stock, we have the ``sell_stock()`` method which takes a number of
stocks a person wishes to sell, and sends the equivalent value in ether to the
seller's address. We first ``assert`` that the number of stocks the person
wishes to sell is a value greater than ``0``. We also ``assert`` to see that
the user can only sell as much as the user owns and that the company has enough
ether to complete the sale. If all conditions are met, the holdings are deducted
from the seller and given to the company. The ethers are then sent to the seller.

.. literalinclude:: ../examples/stock/company.vy
  :language: python
  :pyobject: transfer_stock

A stockholder can also transfer their stock to another stockholder with the
``transfer_stock()`` method. The method takes a receiver address and the number
of shares to send. It first ``asserts`` that the amount being sent is greater
than ``0`` and ``asserts`` whether the sender has enough stocks to send. If
both conditions are satisfied, the transfer is made.

.. literalinclude:: ../examples/stock/company.vy
  :language: python
  :pyobject: pay_bill

The company is also allowed to pay out an amount in ether to an address by
calling the ``pay_bill()`` method. This method should only be callable by the
company and thus first checks whether the method caller's address matches that
of the company. Another important condition to check is that the company has
enough funds to pay the amount. If both conditions satisfy, the contract
sends its ether to an address.

.. literalinclude:: ../examples/stock/company.vy
  :language: python
  :pyobject: debt

We can also check how much the company has raised by multiplying the number of
shares the company has sold and the price of each share. We can get this value
by calling the ``debt()`` method.

.. literalinclude:: ../examples/stock/company.vy
  :language: python
  :pyobject: worth

Finally, in this ``worth()`` method, we can check the worth of a company by
subtracting its debt from its ether balance.

This contract has been the most thorough example so far in terms of its
functionality and features. Yet despite the thoroughness of such a contract, the
logic remained simple. Hopefully, by now, the Vyper language has convinced you
of its capabilities and readability in writing smart contracts.

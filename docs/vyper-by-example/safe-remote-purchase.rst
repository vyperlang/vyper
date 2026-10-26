.. index:: purchases

Safe Remote Purchases
*********************

.. _safe_remote_purchases:

.. warning::

   This is example code for learning purposes. Do not use in production without thorough review and testing.

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

There are certainly other ways of designing a secure escrow system with less
overhead for both the buyer and seller, but for the purpose of this example,
we want to explore one way how an escrow system can be implemented trustlessly.

Let's go!

.. literalinclude:: ../../examples/safe_remote_purchase/safe_remote_purchase.vy
  :language: vyper
  :linenos:

This is also a moderately short contract, however a little more complex in
logic. Let's break down this contract bit by bit.

.. literalinclude:: ../../examples/safe_remote_purchase/safe_remote_purchase.vy
  :language: vyper
  :lineno-start: 18
  :lines: 18-23

Like the other contracts, we begin by declaring our global variables public with
their respective data types. Remember that the ``public`` function allows the
variables to be *readable* by an external caller, but not *writeable*.

.. literalinclude:: ../../examples/safe_remote_purchase/safe_remote_purchase.vy
  :language: vyper
  :lineno-start: 25
  :lines: 25-33

With a ``@payable`` decorator on the constructor, the contract creator will be
required to make an initial deposit equal to twice the item's ``value`` to
initialize the contract, which will be later returned. This is in addition to
the gas fees needed to deploy the contract on the blockchain, which is not
returned. We ``assert`` that the deposit is divisible by 2 to ensure that the
seller deposited a valid amount. The constructor stores the item's value
in the contract variable ``self.value`` and saves the contract creator into
``self.seller``. The contract variable ``self.unlocked`` is initialized to
``True``.

.. literalinclude:: ../../examples/safe_remote_purchase/safe_remote_purchase.vy
  :language: vyper
  :lineno-start: 35
  :lines: 35-43

The ``abort()`` method is a method only callable by the seller and while the
contract is still ``unlocked``—meaning it is callable only prior to any buyer
making a purchase. As we will see in the ``purchase()`` method that when
a buyer calls the ``purchase()`` method and sends a valid amount to the contract,
the contract will be locked and the seller will no longer be able to call
``abort()``.

When the seller calls ``abort()`` and if the ``assert`` statements pass, the
contract sends the balance back to the seller, effectively canceling the sale.

.. literalinclude:: ../../examples/safe_remote_purchase/safe_remote_purchase.vy
  :language: vyper
  :lineno-start: 45
  :lines: 45-53

Like the constructor, the ``purchase()`` method has a ``@payable`` decorator,
meaning it can be called with a payment. For the buyer to make a valid
purchase, we must first ``assert`` that the contract's ``unlocked`` property is
``True`` and that the amount sent is equal to twice the item's value. We then
set the buyer to the ``msg.sender`` and lock the contract. At this point, the
contract has a balance equal to 4 times the item value and the seller must
send the item to the buyer.

.. literalinclude:: ../../examples/safe_remote_purchase/safe_remote_purchase.vy
  :language: vyper
  :lineno-start: 55
  :lines: 55-72

Finally, upon the buyer's receipt of the item, the buyer can confirm their
receipt by calling the ``received()`` method to distribute the funds as
intended—where the seller receives 3/4 of the contract balance and the buyer
receives 1/4.

By calling ``received()``, we begin by checking that the contract is indeed
locked, ensuring that a buyer had previously paid. We also ensure that this
method is only callable by the buyer. If these two ``assert`` statements pass,
we refund the buyer their initial deposit and send the seller the remaining
funds, completing the transaction.

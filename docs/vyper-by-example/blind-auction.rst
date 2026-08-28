.. index:: auction;blind, blind auction

Blind Auction
*************

.. _blind_auction:

.. warning::

   This is example code for learning purposes. Do not use in production without thorough review and testing.

Before we dive into our other examples, let's briefly explore another type of
auction that you can build with Vyper. Similar to blind auction examples in
Solidity, this contract allows for an auction where there is no time pressure towards the end of the bidding period.

.. literalinclude:: ../../examples/auctions/blind_auction.vy
  :language: vyper
  :linenos:

While this blind auction is almost functionally identical to the blind auction implemented in Solidity, the differences in their implementations help illustrate the differences between Solidity and Vyper.

.. literalinclude:: ../../examples/auctions/blind_auction.vy
  :language: vyper
  :lineno-start: 9
  :lines: 9-12

One difference is that in this example, we use a fixed-size array, limiting the number of bids that can be placed by one address to 128 in this
example. Bidders who want to make more than this maximum number of bids would
need to do so from multiple addresses.

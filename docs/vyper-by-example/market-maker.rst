.. index:: market maker, AMM

.. _market_maker:

On-Chain Market Maker
*********************

.. warning::

   This is example code for learning purposes. Do not use in production without thorough review and testing.

A simple automated market maker (AMM) using the constant product formula (x * y = k).

.. literalinclude:: ../../examples/market_maker/on_chain_market_maker.vy
  :language: vyper
  :linenos:

How it works:

1. Owner calls ``initiate()`` with initial ETH and tokens, setting the invariant (k = ETH * tokens)
2. Users swap ETH for tokens via ``ethToTokens()``
3. Users swap tokens for ETH via ``tokensToEth()``
4. The invariant is maintained: more ETH in = fewer tokens out

The 0.2% fee (``msg.value // 500``) on ETH-to-token swaps goes to the liquidity provider.

.. note::

   Production AMMs need price oracles, slippage protection, and liquidity management.
   This example demonstrates the core swap mechanism only.

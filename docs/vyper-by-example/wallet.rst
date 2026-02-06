.. index:: wallet, multisig

Multi-Signature Wallet
**********************

.. _wallet:

.. warning::

   This is example code for learning purposes. Do not use in production without thorough review and testing.

A multi-signature wallet requiring multiple owner approvals to execute transactions.

.. literalinclude:: ../../examples/wallet/wallet.vy
  :language: vyper
  :linenos:

Key concepts:

- **Threshold signatures**: Requires ``threshold`` out of 5 owners to approve
- **Signature verification**: Uses ``ecrecover`` to verify owner signatures
- **Replay protection**: ``seq`` counter prevents transaction replay
- **Arbitrary calls**: ``raw_call`` executes any transaction once approved

The approval process:

1. Owners sign a hash of (sequence number, destination, value, data)
2. Anyone can call ``approve()`` with the collected signatures
3. If enough valid signatures are provided, the transaction executes

.. note::

   This demonstrates signature verification patterns. Production multisigs
   need additional safeguards like time locks and nonce management.

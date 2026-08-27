.. index:: tokens;ERC20, ERC20

.. _erc20:

ERC20 Token
***********

.. warning::

   This is example code for learning purposes. Do not use in production without thorough review and testing.

A standard ERC20 fungible token implementation.

.. literalinclude:: ../../examples/tokens/ERC20.vy
  :language: vyper
  :linenos:

Key features:

- Implements the ``IERC20`` and ``IERC20Detailed`` interfaces from ``ethereum.ercs``
- Standard ``transfer``, ``transferFrom``, and ``approve`` functions
- ``mint`` and ``burn`` functions for supply management
- Uses ``HashMap`` for balances and allowances

.. note::

   This is example code. Production tokens require additional security review.

Notice how Vyper's overflow/underflow protection is built-in: the comment "vyper does not allow underflows"
explains why no explicit check is needed when subtracting from balances.

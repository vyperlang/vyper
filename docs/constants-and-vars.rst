.. index:: type

.. _types:

Constants and Environment Variables
***********************************

.. _types-constants:

Built In Constants
==================

Vyper has a few convenience constants builtin.

================= ================ ==============================================
Name              Type             Value
================= ================ ==============================================
``ZERO_ADDRESS``  ``address``      ``0x0000000000000000000000000000000000000000``
``EMPTY_BYTES32`` ``bytes32``      ``0x0000000000000000000000000000000000000000000000000000000000000000``
``MAX_INT128``    ``int128``       ``2**127 - 1``
``MIN_INT128``    ``int128``       ``-2**127``
``MAX_DECIMAL``   ``decimal``      ``(2**127 - 1)``
``MIN_DECIMAL``   ``decimal``      ``(-2**127)``
``MAX_UINT256``   ``uint256``      ``2**256 - 1``
``ZERO_WEI``      ``uint256(wei)`` ``0``
================= ================ ==============================================

Custom Constants
================

Custom constants can be defined at a global level in Vyper. To define a constant make use of the ``constant`` keyword.

**Example:**
::

  TOTAL_SUPPLY: constant(uint256) = 10000000
  total_supply: public(uint256)

  @public
  def __init__():
      self.total_supply = TOTAL_SUPPLY

**Advanced Example:**
::

  units: {
      share: "Share unit"
  }

  MAX_SHARES: constant(uint256(share)) = 1000
  SHARE_PRICE: constant(uint256(wei/share)) = 5

  @public
  def market_cap() -> uint256(wei):
      return MAX_SHARES * SHARE_PRICE

.. _types-env-vars:

Environment Variables
=====================

Environment variables always exist in the namespace and are used to provide information about the blockchain or current transaction.

.. note::

    ``msg.sender`` and ``msg.value`` can only be accessed from public functions. If you require these values within a private function they must be passed as parameters.

==================== ================ =============================================
Name                 Type             Value
==================== ================ =============================================
``block.coinbase``   ``address``      Current block miner’s address
``block.difficulty`` ``uint256``      Current block difficulty
``block.number``     ``uint256``      Current block number
``block.prevhash``   ``bytes32``      Equivalent to ``blockhash(block.number - 1)``
``block.timestamp``  ``uint256``      Current block epoch timestamp
``chain.id``         ``uint256``      Chain ID
``msg.gas``          ``uint256``      Remaining gas
``msg.sender``       ``address``      Sender of the message (current call)
``msg.value``        ``uint256(wei)`` Number of wei sent with the message
``tx.origin``        ``address``      Sender of the transaction (full call chain)
==================== ================ =============================================

Environment Variables and Constants
###################################

.. _types-env-vars:

Environment Variables
=====================

Environment variables always exist in the namespace and are primarily used to provide information about the blockchain or current transaction.

Block and Transaction Properties
--------------------------------

==================== ================ =============================================
Name                 Type             Value
==================== ================ =============================================
``block.coinbase``   ``address``      Current block miner’s address
``block.difficulty`` ``uint256``      Current block difficulty
``block.number``     ``uint256``      Current block number
``block.prevhash``   ``bytes32``      Equivalent to ``blockhash(block.number - 1)``
``block.timestamp``  ``uint256``      Current block epoch timestamp
``chain.id``         ``uint256``      Chain ID
``msg.data``         ``Bytes``        Message data
``msg.gas``          ``uint256``      Remaining gas
``msg.sender``       ``address``      Sender of the message (current call)
``msg.value``        ``uint256``      Number of wei sent with the message
``tx.origin``        ``address``      Sender of the transaction (full call chain)
``tx.gasprice``      ``uint256``      Gas price of current transaction in wei
==================== ================ =============================================

.. note::

    ``msg.data`` requires the usage of :func:`slice <slice>` to explicitly extract a section of calldata. If the extracted section exceeds the bounds of calldata, this will throw. You can check the size of ``msg.data`` using :func:`len <len>`.

.. _constants-self:

The self Variable
-----------------

``self`` is an environment variable used to reference a contract from within itself. Along with the normal :ref:`address<address>` members, ``self`` allows you to read and write to state variables and to call private functions within the contract.

==================== ================ ==========================
Name                 Type             Value
==================== ================ ==========================
``self``             ``address``      Current contract's address
``self.balance``     ``uint256``      Current contract's balance
==================== ================ ==========================

Accessing State Variables
~~~~~~~~~~~~~~~~~~~~~~~~~

``self`` is used to access a contract's :ref:`state variables<structure-state-variables>`, as shown in the following example:

.. code-block:: python

    state_var: uint256

    @external
    def set_var(value: uint256) -> bool:
        self.state_var = value
        return True

    @external
    @view
    def get_var() -> uint256:
        return self.state_var


Calling Internal Functions
~~~~~~~~~~~~~~~~~~~~~~~~~~

``self`` is also used to call :ref:`internal functions<structure-functions-internal>` within a contract:

.. code-block:: python

    @internal
    def _times_two(amount: uint256) -> uint256:
        return amount * 2

    @external
    def calculate(amount: uint256) -> uint256:
        return self._times_two(amount)

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
================= ================ ==============================================

Custom Constants
================

Custom constants can be defined at a global level in Vyper. To define a constant, make use of the ``constant`` keyword.

.. code-block:: python

    TOTAL_SUPPLY: constant(uint256) = 10000000
    total_supply: public(uint256)

    @external
    def __init__():
        self.total_supply = TOTAL_SUPPLY

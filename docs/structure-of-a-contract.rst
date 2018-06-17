.. index:: contract, state variable, function, metadata;

.. _contract_structure:

***********************
Structure of a Contract
***********************

Contracts in Vyper are contained within files, with each file being one smart-contract.  Files in Vyper are similar to classes in object-oriented languages.
Each file can contain declarations of :ref:`structure-state-variables`, :ref:`structure-functions`, and :ref:`structure-structs-types`.

.. _structure-state-variables:

State Variables
===============

State variables are values which are permanently stored in contract storage.

::

  storedData: int128

See the :ref:`types` section for valid state variable types and
:ref:`visibility-and-getters` for possible choices for
visibility.

.. _structure-functions:

Functions
=========

Functions are the executable units of code within a contract.

::

  @public
  @payable
  def bid(): // Function
    // ...

:ref:`Function-calls` can happen internally or externally
and have different levels of visibility (:ref:`visibility-and-getters`)
towards other contracts. Functions must be decorated with either @public or @private.

.. _structure-events:

Events
======

Events may be logged in specially indexed data structures that allow clients, including light clients, to efficiently search for them.

::

    Payment: event({amount: int128, arg2: indexed(address)})

    total_paid: int128

    @public
    @payable
    def pay():
        self.total_paid += msg.value
        log.Payment(msg.value, msg.sender)

Events must be declared before global declarations and function definitions.

.. structure-metedata:

NatSpec Metadata
================

Vyper supports structured documentation for state variables and functions and events.

::

  # @author Bob Clampett
  # @notice Number of carrots eaten
  # @dev Chewing does not count, carrots must pass the throat to be "eaten"
  carrotsEaten: int128

::

  # @author Bob Clampett
  # @notice Determine if Bugs will accept `food` to eat
  # @dev Compares the entire string and does not rely on a hash
  # @param food The name of a food to evaluate (in English)
  # @return true if Bugs will eat it, false otherwise
  @public
  @payable
  def doesEat(food: string):
    // ...

::

  # @author Bob Clampett
  # @notice Bugs did eat `food`
  # @dev Chewing does not count, carrots must pass the throat to be "eaten"
  # @param food The name of a food that was eaten (in English)
  Ate: event({food: string})


Additional information about Ethereum Natural Specification (NatSpec) can be found `here <https://github.com/ethereum/wiki/wiki/Ethereum-Natural-Specification-Format>`_. 

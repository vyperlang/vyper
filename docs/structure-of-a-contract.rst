.. index:: contract, state variable, function;

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

Default function
----------------

A contract can also have a default function, which is executed on a call to the contract if no other functions match the given function identifier (or if none was supplied at all, such as through someone sending it Eth). It is the same construct as fallback functions `in Solidity <https://solidity.readthedocs.io/en/latest/contracts.html?highlight=fallback#fallback-function>`_. 

This function is always named `__default__` and must be annotated with `@public` and `@payable`. It cannot have arguments and cannot return anything.

Furthermore, this function is executed whenever the contract receives plain Ether (without data). This is why the default function cannot accept arguments and return values - it is a design decision of Ethereum to make no differentiation between sending ether to a contract or a user address.

**Example:**

::

    Sent: event({sender: indexed(address)})
    
    @public
    @payable
    def __default__():
        log.Sent(msg.sender)


Considerations
~~~~~~~~~~~~~~

Unlike Solidity, Vyper generates a default function is one isn't found, in the form of a REVERT call. Note that this still `generates an exception <https://github.com/ethereum/wiki/wiki/Subtleties>`_ and thus will not succeed in receiving funds. 

Send calls to the contract give it a maximum stipend of 2300 gas, leaving not much room to perform other operations except basic logging. The following operations will consume more gas than the 2300 gas stipend:

- Writing to storage
- Creating a contract
- Calling an external function which consumes a large amount of gas
- Sending Ether

Since global variables are still accessible, you can pass data to the default function through the raw byte buffer provided to EVM's CALL (`msg.data`).

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

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

  storedData: num

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
  }

:ref:`Function-calls` can happen internally or externally
and have different levels of visibility (:ref:`visibility-and-getters`)
towards other contracts. Functions must be decorated with either @public or @private.

.. _structure-events:

Events
======

Events may be logged in specially indexed data structures that allow clients, including light clients, to efficiently search for them.

::

    Payment: __log__({amount: num, arg2: indexed(address)})

    total_paid: num

    @public
    def pay():
        self.total_paid += msg.value
        log.Payment(msg.value, msg.sender)

Events must be declared before global declarations and function definitions.

.. index:: contract, state variable, function, event, struct, enum, function;modifier

.. _contract_structure:

***********************
Structure of a Contract
***********************

Contracts in Viper are contained within files, with each file being one smart-contract.  Files in Viper are similar to classes in object-oriented languages.
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

  @payable
  function bid(): // Function
    // ...
  }

:ref:`function-calls` can happen internally or externally
and have different levels of visibility (:ref:`visibility-and-getters`)
towards other contracts.



.. _structure-structs-types:

Structs Types
=============

Structs are custom defined types that can group several variables (see
:ref:`structs` in types section).

::

    # Information about voters
    voters: public({
        # weight is accumulated by delegation
        weight: num,
        # if true, that person already voted
        voted: bool,
        # person delegated to
        delegate: address,
        # index of the voted proposal
        vote: num
    })
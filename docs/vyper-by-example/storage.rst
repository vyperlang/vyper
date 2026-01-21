.. index:: storage

Storage Patterns
****************

.. _simple_storage:

.. warning::

   This is example code for learning purposes. Do not use in production without thorough review and testing.

Let's start with a minimal contract that demonstrates state storage.
This contract stores a single integer that can be set by anyone.

Simple Storage
==============

.. literalinclude:: ../../examples/storage/storage.vy
  :language: vyper
  :linenos:

This example shows:

- A public state variable ``storedData`` with an auto-generated getter
- A constructor (``__init__``) that sets the initial value
- An external function ``set()`` that modifies state

The ``public`` modifier on ``storedData`` automatically creates a getter function,
so external contracts can read the value by calling ``contract.storedData()``.

.. index:: storage;advanced

.. _advanced_storage:

Advanced Storage
================

Building on the simple storage example, this contract adds input validation,
events, and a reset function.

.. literalinclude:: ../../examples/storage/advanced_storage.vy
  :language: vyper
  :linenos:

New concepts introduced:

- **Events**: The ``DataChange`` event logs who changed the value and what they changed it to. The ``indexed`` keyword allows filtering by the setter's address.
- **Assertions with messages**: ``assert _x >= 0, "No negative values"`` reverts with a readable error.
- **Business logic guards**: The contract locks when the stored value reaches 100.

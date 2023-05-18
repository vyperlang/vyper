.. _contract_structure:

Structure of a Contract
#######################

Vyper contracts are contained within files. Each file contains exactly one contract.

This section provides a quick overview of the types of data present within a contract, with links to other sections where you can obtain more details.

.. _structure-versions:

Version Pragma
==============

Vyper supports a version pragma to ensure that a contract is only compiled by the intended compiler version, or range of versions. Version strings use `NPM <https://docs.npmjs.com/about-semantic-versioning>`_ style syntax.

.. code-block:: python

    # @version ^0.2.0

In the above example, the contract only compiles with Vyper versions ``0.2.x``.

.. _structure-state-variables:

State Variables
===============

State variables are values which are permanently stored in contract storage. They are declared outside of the body of any functions, and initially contain the :ref:`default value<types-initial>` for their type.

.. code-block:: python

    storedData: int128

State variables are accessed via the :ref:`self<constants-self>` object.

.. code-block:: python

    self.storedData = 123

See the documentation on :ref:`Types<types>` or :ref:`Scoping and Declarations<scoping>` for more information.

.. _structure-functions:

Functions
=========

Functions are executable units of code within a contract.

.. code-block:: python

    @external
    def bid():
        ...

Functions may be called internally or externally depending on their :ref:`visibility <function-visibility>`. Functions may accept input arguments and return variables in order to pass values between them.

See the :ref:`Functions <control-structures-functions>` documentation for more information.

Events
======

Events provide an interface for the EVM's logging facilities. Events may be logged with specially indexed data structures that allow clients, including light clients, to efficiently search for them.

.. code-block:: python

    event Payment:
        amount: int128
        sender: indexed(address)

    total_paid: int128

    @external
    @payable
    def pay():
        self.total_paid += msg.value
        log Payment(msg.value, msg.sender)

See the :ref:`Event <event-logging>` documentation for more information.

Interfaces
==========

An interface is a set of function definitions used to enable calls between smart contracts. A contract interface defines all of that contract's externally available functions. By importing the interface, your contract now knows how to call these functions in other contracts.

Interfaces can be added to contracts either through inline definition, or by importing them from a separate file.

.. code-block:: python

    interface FooBar:
        def calculate() -> uint256: view
        def test1(): nonpayable

.. code-block:: python

    from foo import FooBar

Once defined, an interface can then be used to make external calls to a given address:

.. code-block:: python

    @external
    def test(some_address: address):
        FooBar(some_address).calculate()

See the :ref:`Interfaces <interfaces>` documentation for more information.

Structs
=======

A struct is a custom defined type that allows you to group several variables together:

.. code-block:: python

    struct MyStruct:
        value1: int128
        value2: decimal

See the :ref:`Structs <types-struct>` documentation for more information.

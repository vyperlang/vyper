.. _contract_structure:

Structure of a Contract
#######################

Vyper contracts are contained within files. Each file contains exactly one contract.

This section provides a quick overview of the types of data present within a contract, with links to other sections where you can obtain more details.

.. _structure-versions:

Pragmas
=======

Vyper supports several source code directives to control compiler modes and help with build reproducibility.

Version Pragma
--------------

The version pragma ensures that a contract is only compiled by the intended compiler version, or range of versions. Version strings use `NPM <https://docs.npmjs.com/about-semantic-versioning>`_ style syntax. Starting from v0.4.0 and up, version strings will use `PEP440 version specifiers <https://peps.python.org/pep-0440/#version-specifiers>`_.

As of 0.3.10, the recommended way to specify the version pragma is as follows:

.. code-block:: vyper

    #pragma version ^0.3.0

.. note::

    Both pragma directive versions ``#pragma`` and ``# pragma`` are supported.

The following declaration is equivalent, and, prior to 0.3.10, was the only supported method to specify the compiler version:

.. code-block:: vyper

    # @version ^0.3.0


In the above examples, the contract will only compile with Vyper versions ``0.3.x``.

Optimization Mode
-----------------

The optimization mode can be one of ``"none"``, ``"codesize"``, or ``"gas"`` (default). For example, adding the following line to a contract will cause it to try to optimize for codesize:

.. code-block:: vyper

   #pragma optimize codesize

The optimization mode can also be set as a compiler option, which is documented in :ref:`optimization-mode`. If the compiler option conflicts with the source code pragma, an exception will be raised and compilation will not continue.

EVM Version
-----------------

The EVM version can be set with the ``evm-version`` pragma, which is documented in :ref:`evm-version`.


.. _structure-state-variables:

State Variables
===============

State variables are values which are permanently stored in contract storage. They are declared outside of the body of any functions, and initially contain the :ref:`default value<types-initial>` for their type.

.. code-block:: vyper

    storedData: int128

State variables are accessed via the :ref:`self<constants-self>` object.

.. code-block:: vyper

    self.storedData = 123

See the documentation on :ref:`Types<types>` or :ref:`Scoping and Declarations<scoping>` for more information.

.. _structure-functions:

Functions
=========

Functions are executable units of code within a contract.

.. code-block:: vyper

    @external
    def bid():
        ...

Functions may be called internally or externally depending on their :ref:`visibility <function-visibility>`. Functions may accept input arguments and return variables in order to pass values between them.

See the :ref:`Functions <control-structures-functions>` documentation for more information.

Events
======

Events provide an interface for the EVM's logging facilities. Events may be logged with specially indexed data structures that allow clients, including light clients, to efficiently search for them.

.. code-block:: vyper

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

.. code-block:: vyper

    interface FooBar:
        def calculate() -> uint256: view
        def test1(): nonpayable

.. code-block:: vyper

    from foo import FooBar

Once defined, an interface can then be used to make external calls to a given address:

.. code-block:: vyper

    @external
    def test(some_address: address):
        FooBar(some_address).calculate()

See the :ref:`Interfaces <interfaces>` documentation for more information.

Structs
=======

A struct is a custom defined type that allows you to group several variables together:

.. code-block:: vyper

    struct MyStruct:
        value1: int128
        value2: decimal

See the :ref:`Structs <types-struct>` documentation for more information.

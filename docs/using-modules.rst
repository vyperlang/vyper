.. _modules:

Modules
#######

A module is a set of function definitions and variable declarations which enables code reuse. Vyper favors code reuse through composition, rather than inheritance. A module encapsulates everything needed for code reuse, from type and function declarations to state.

Declaring and using modules
===========================

The simplest way to define a module is to write a contract. In Vyper, any contract is a valid module! For example, the following contract is also a valid module.

.. code-block:: vyper

    # ownable.vy

    owner: address

    @deploy
    def __init__():
        self.owner = msg.sender

    def _check_owner():
        assert self.owner == msg.sender

    @pure
    def _times_two(x: uint256) -> uint256:
        return x * 2

    @external
    def update_owner(new_owner: address):
        self._check_owner()

        self.owner = new_owner

This contract basically has two bits of functionality which can be reused upon import, the ``_check_owner()`` function and the ``update_owner()`` function. The ``_check_owner()`` is an internal function which can be used as a helper to check ownership in importing modules, while the ``update_owner()`` is an external function which an importing module can export as an externally facing piece of functionality.

You can use this module's functionality simply by importing it, however any functionality that you do not use from a module will not be included in the final compilation target. For example, if you don't use the ``initializes`` statement to declare a module's location in the storage layout, you cannot use its state. Similarly, if you don't explicitly ``export`` an external function from a module, it will not appear in the runtime code.

Importing a module
==================

A module can be imported using ``import`` or ``from ... import`` statements. The following are all equivalent ways to import the above module:

.. code-block:: vyper

    import ownable               # accessible as ownable.<function>
    import ownable as ow         # accessible as ow.<function>
    from . import ownable        # accessible as ownable.<function>
    from . import ownable as ow  # accessible as ow.<function>

When importing using the ``as`` keyword, the module will be referred to by its alias in the rest of the contract.

The ``_times_two()`` helper function in the above module can be immediately used without any further work.

.. code-block:: vyper

    import ownable as helper
    @external
    def my_function(x: uint256) -> uint256:
        return helper._times_two(x)

The other functions cannot be used yet, because they touch the ``ownable`` module's state. There are two ways to declare a module so that its state can be used.

Initializing a module
=====================

In order to use a module's state, it must be "initialized". A module can be initialized with the ``initializes`` keyword. This declares the module's location in the contract's :ref:`Storage Layout <compiler-storage-layout>`. It also creates a requirement to invoke the module's :ref:`__init__() <init-function>`, if it has one. This is a well-formedness requirement, since it does not make sense to access a module's state unless its ``__init__()`` function has been called.

.. code-block:: vyper

    import ownable

    initializes: ownable

    @deploy
    def __init__():
        ownable.__init__()

    @external
    def access_controlled_function():
        ownable._check_owner()  # reverts unless msg.sender == ownable.owner

        ... # do things that only the owner can do

It is a compile-time error to invoke a module's ``__init__`` function more than once!

A module's state can be directly accessed (TK example)


The ``uses`` statement
======================

Another way of using a contract's state without directly initializing it is to use the ``uses`` keyword. This is a more advanced usage which is expected to be mostly utilized by library designers, which allows a module to use another module's state but defer its initialization to another module in the compilation tree (most likely a user of the library in question).

This is best illustrated with an example:

.. code-block:: vyper

    # ownable_2step.vy
    import ownable

    uses: ownable

    # does not export ownable.transfer_ownership!

    pending_owner: address  # TK explanation

    @deploy
    def __init__():
        self.pending_owner = empty(address)

    @external
    def begin_transfer(new_owner: address):
        ownable._check_owner()

        self.pending_owner = new_owner

    @external
    def accept_transfer():
        assert msg.sender == self.pending_owner

        self.owner = new_owner

Here, the ``ownable_2step`` module does not want to seal off access to calling the ``ownable`` module's ``__init__()`` function. So, it utilizes the ``uses: ownable`` statement to get access to the ``ownable`` module's state, without the requirement to initialize it.

This design takes inspiration from (but is unrelated to) the rust language's `borrow checker <https://doc.rust-lang.org/1.8.0/book/references-and-borrowing.html>_`. In the language of type systems, module is initialization is modeled as an affine constraint which is promoted to a linear constraint if the module's state is touched in the compilation target. In practice, what this means is:

* A module must be "used" or "initialized" before its state can be accessed in an import
* A module may be "used" many times
* A module which is used or its state touched must be initialized exactly once

Whether to ``use`` or ``initialize`` a module is a choice which is left up to the library designer.



.. _modules:

Modules
#######

A module is a set of function definitions and variable declarations which enables code reuse. Vyper favors code reuse through composition, rather than inheritance. A module encapsulates everything needed for code reuse, from type and function declarations to state. It is important to note that functions which make use of defined state must be initialized in order to use that state, whereas functions that are "pure" do not require this.

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

This contract basically has two bits of functionality which can be reused upon import, the ``_check_owner()`` function and the ``update_owner()`` function. The ``_check_owner()`` is an internal function which can be used as a helper to check ownership in importing modules, while the ``update_owner()`` is an external function which an importing module can itself :ref:`export <exporting-functions>` as an externally facing piece of functionality.

You can use this module's functionality simply by importing it, however any functionality that you do not use from a module will not be included in the final compilation target. For example, if you don't use the ``initializes`` statement to declare a module's location in the storage layout, you cannot use its state. Similarly, if you don't explicitly ``export`` an external function from a module, it will not appear in the runtime code.

Importing a module
==================

A module can be imported using ``import`` or ``from ... import`` statements. The following are all equivalent ways to import the above module:

.. code-block:: vyper

    import ownable               # accessible as `ownable`
    import ownable as ow         # accessible as `ow`
    from . import ownable        # accessible as `ownable`
    from . import ownable as ow  # accessible as `ow`

When importing using the ``as`` keyword, the module will be referred to by its alias in the rest of the contract.

The ``_times_two()`` helper function in the above module can be immediately used without any further work since it is "pure" and doesn't depend on initialized state.

.. code-block:: vyper

    import ownable as helper
    @external
    def my_function(x: uint256) -> uint256:
        return helper._times_two(x)

The other functions cannot be used yet, because they touch the ``ownable`` module's state. There are two ways to declare a module so that its state can be used.

Using a module as an interface
==============================

A module can be used as an interface with the ``__at__`` syntax.

.. code-block:: vyper

    import ownable

    an_ownable: ownable.__interface__

    def call_ownable(addr: address):
        self.an_ownable = ownable.__at__(addr)
        self.an_ownable.transfer_ownership(...)

Initializing a module
=====================

In order to use a module's state, it must be "initialized". A module can be initialized with the ``initializes`` keyword. This declares the module's location in the contract's :ref:`Storage Layout <compiler-storage-layout>`. It also creates a requirement to invoke the module's :ref:`__init__() function <init-function>`, if it has one. This is a well-formedness requirement, since it does not make sense to access a module's state unless its ``__init__()`` function has been called.

.. code-block:: vyper

    import ownable

    initializes: ownable

    @deploy
    def __init__():
        ownable.__init__()

    @external
    def my_access_controlled_function():
        ownable._check_owner()  # reverts unless msg.sender == ownable.owner

        ... # do things that only the owner can do

It is a compile-time error to invoke a module's ``__init__()`` function more than once!

A module's state can be directly accessed just by prefixing the name of a variable with the module's alias, like follows:

.. code-block:: vyper

    @external
    def get_owner() -> address:
        return ownable.owner


The ``uses`` statement
======================

Another way of using a contract's state without directly initializing it is to use the ``uses`` keyword. This is a more advanced usage which is expected to be mostly utilized by library designers. The ``uses`` statement allows a module to use another module's state but defer its initialization to another module in the compilation tree (most likely a user of the library in question).

This is best illustrated with an example:

.. code-block:: vyper

    # ownable_2step.vy
    import ownable

    uses: ownable

    # does not export ownable.transfer_ownership!

    pending_owner: address  # the pending owner in the 2-step transfer process

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

        ownable.owner = new_owner
        self.pending_owner = empty(address)

Here, the ``ownable_2step`` module does not want to seal off access to calling the ``ownable`` module's ``__init__()`` function. So, it utilizes the ``uses: ownable`` statement to get access to the ``ownable`` module's state, without the requirement to initialize it. Note that this is a valid module, but it is not a valid contract (that is, it cannot produce bytecode) because it does not initialize the ``ownable`` module. To make a valid contract, the user of the ``ownable_2step`` module would be responsible for initializing the ``ownable`` module themselves (as in the next section: :ref:`initializing dependencies <init-dependencies>`).

Whether to ``use`` or ``initialize`` a module is a choice which is left up to the library designer.

Technical notes on the design
-----------------------------

This section contains some notes on the design from a language design perspective. It can be safely skipped if you are just interested in how to use modules, and not necessarily in programming language theory.

The design of the module system takes inspiration from (but is not directly related to) the rust language's `borrow checker <https://doc.rust-lang.org/1.8.0/book/references-and-borrowing.html>`_. In the language of type systems, module initialization is modeled as an affine constraint which is promoted to a linear constraint if the module's state is touched in the compilation target. In practice, what this means is:

* A module must be "used" or "initialized" before its state can be accessed in an import
* A module may be "used" many times
* A module which is "used" or its state touched must be "initialized" exactly once

To read more about the design background of Vyper's module system, please see its original `design document <https://github.com/vyperlang/vyper/issues/3722>`_.

.. _init-dependencies:

Initializing a module with dependencies
=======================================

Sometimes, you may encounter a module which itself ``uses`` other modules. Vyper's module system is designed to allow this, but it requires you make explicit the access to the imported module's state. The above ``ownable_2step.vy`` contract is an example of this. If you wanted to initialize the ``ownable_2step`` module, it would use the special ``:=`` (aka "walrus") syntax, and look something like this:

.. code-block:: vyper

    import ownable
    import ownable_2step

    initializes: ownable

    # ownable is explicitly declared as a state dependency of `ownable_2step`
    initializes: ownable_2step[ownable := ownable]

    @deploy
    def __init__():
        ownable.__init__()
        ownable_2step.__init__()

    # export all external functions from ownable_2step
    exports: ownable_2step.__interface__

.. warning::
    In normal usage, you should make sure that ``__init__()`` functions are called in dependency order. In the above example, you can get unexpected behavior if ``ownable_2step.__init__()`` is called before ``ownable.__init__()``! The compiler may enforce this behavior in the future.

.. _exporting-functions:

Exporting functions
===================

In Vyper, ``@external`` functions are not automatically exposed (i.e., included in the runtime code) in the importing contract. This is a safety feature, it means that any externally facing functionality must be explicitly defined in the top-level of the compilation target.

So, exporting external functions from modules is accomplished using the ``exports`` keyword. In Vyper, functions can be exported individually, or, a wholesale export of all the functions in an interface can be done. The special interface ``module.__interface__`` is a compiler-defined interface, which automatically includes all the functions in a module.

The following are all ways of exporting functions from an imported module.

.. code-block:: vyper

    # export a single function from `ownable_2step`
    exports: ownable_2step.transfer_ownership

    # export multiple functions from `ownable_2step`, being explicit about
    # which specific functions are being exported
    exports: (
        ownable_2step.transfer_ownership,
        ownable_2step.accept_ownership,
    )

    # export all IERC20 functions from `base_token`
    exports: base_token.IERC20

    # export all external functions from `ownable_2step`
    exports: ownable_2step.__interface__

.. note::
    Any exported interfaces must be implemented by the module. For example, in the above example, ``base_token`` must contain ``implements: IERC20``, or else the compiler will raise an error.

.. _interfaces:

Interfaces
##########

An interface is a set of function definitions used to enable communication between smart contracts. A contract interface defines all of that contract's externally available functions. By importing the interface, your contract now knows how to call these functions in other contracts.

Declaring and using Interfaces
==============================

Interfaces can be added to contracts either through inline definition, or by importing them from a separate file.

The ``interface`` keyword is used to define an inline external interface:

.. code-block:: vyper

    interface FooBar:
        def calculate() -> uint256: view
        def test1(): nonpayable

The defined interface can then be used to make external calls, given a contract address:

.. code-block:: vyper

    @external
    def test(foobar: FooBar):
        foobar.calculate()

The interface name can also be used as a type annotation for storage variables. You then assign an address value to the variable to access that interface. Note that casting an address to an interface is possible, e.g. ``FooBar(<address_var>)``:

.. code-block:: vyper

    foobar_contract: FooBar

    @external
    def __init__(foobar_address: address):
        self.foobar_contract = FooBar(foobar_address)

    @external
    def test():
        self.foobar_contract.calculate()

Specifying ``payable`` or ``nonpayable`` annotation indicates that the call made to the external contract will be able to alter storage, whereas the ``view`` ``pure`` call will use a ``STATICCALL`` ensuring no storage can be altered during execution. Additionally, ``payable`` allows non-zero value to be sent along with the call.

.. code-block:: vyper

    interface FooBar:
        def calculate() -> uint256: pure
        def query() -> uint256: view
        def update(): nonpayable
        def pay(): payable

    @external
    def test(foobar: FooBar):
        foobar.calculate()  # cannot change storage
        foobar.query()  # cannot change storage, but reads itself
        foobar.update()  # storage can be altered
        foobar.pay(value=1)  # storage can be altered, and value can be sent

Vyper offers the option to set the following additional keyword arguments when making external calls:

=============================== ===========================================================
Keyword                         Description
=============================== ===========================================================
``gas``                         Specify gas value for the call
``value``                       Specify amount of ether sent with the call
``skip_contract_check``         Drop ``EXTCODESIZE`` and ``RETURNDATASIZE`` checks
``default_return_value``        Specify a default return value if no value is returned
=============================== ===========================================================

The ``default_return_value`` parameter can be used to handle ERC20 tokens affected by the missing return value bug in a way similar to OpenZeppelin's ``safeTransfer`` for Solidity:

.. code-block:: vyper

    IERC20(USDT).transfer(msg.sender, 1, default_return_value=True) # returns True
    IERC20(USDT).transfer(msg.sender, 1) # reverts because nothing returned

.. warning::

   When ``skip_contract_check=True`` is used and the called function returns data (ex.: ``x: uint256 = SomeContract.foo(skip_contract_check=True)``, no guarantees are provided by the compiler as to the validity of the returned value. In other words, it is undefined behavior what happens if the called contract did not exist. In particular, the returned value might point to garbage memory. It is therefore recommended to only use ``skip_contract_check=True`` to call contracts which have been manually ensured to exist at the time of the call.

Importing Interfaces
====================

Interfaces are imported with ``import`` or ``from ... import`` statements.

Imported interfaces are written using standard Vyper syntax. The body of each function is ignored when the interface is imported. If you are defining a standalone interface, it is normally specified by using a ``pass`` statement:

.. code-block:: vyper

    @external
    def test1():
        pass

    @external
    def calculate() -> uint256:
        pass

You can also import a fully implemented contract and Vyper will automatically convert it to an interface. It is even possible for a contract to import itself to gain access to its own interface.

.. code-block:: vyper

    import greeter as Greeter

    name: public(String[10])

    @external
    def __init__(_name: String[10]):
        self.name = _name

    @view
    @external
    def greet() -> String[16]:
        return concat("Hello ", Greeter(msg.sender).name())

Imports via ``import``
----------------------

With absolute ``import`` statements, you **must** include an alias as a name for the imported package. In the following example, failing to include ``as Foo`` will raise a compile error:

.. code-block:: vyper

    import contract.foo as Foo

Imports via ``from ... import``
-------------------------------

Using ``from`` you can perform both absolute and relative imports. You may optionally include an alias - if you do not, the name of the interface will be the same as the file.

.. code-block:: vyper

    # without an alias
    from contract import foo

    # with an alias
    from contract import foo as Foo

Relative imports are possible by prepending dots to the contract name. A single leading dot indicates a relative import starting with the current package. Two leading dots indicate a relative import from the parent of the current package:

.. code-block:: vyper

    from . import foo
    from ..interfaces import baz

.. _searching_for_imports:

Searching For Interface Files
-----------------------------

When looking for a file to import, Vyper will first search relative to the same folder as the contract being compiled. For absolute imports, it also searches relative to the root path for the project. Vyper checks for the file name with a ``.vy`` suffix first, then ``.json``.

When using the command line compiler, the root path defaults to the current working directory. You can change it with the ``-p`` flag:

::

    $ vyper my_project/contracts/my_contract.vy -p my_project

In the above example, the ``my_project`` folder is set as the root path. A contract cannot perform a relative import that goes beyond the top-level folder.

Built-in Interfaces
===================

Vyper includes common built-in interfaces such as `ERC20 <https://eips.ethereum.org/EIPS/eip-20>`_ and `ERC721 <https://eips.ethereum.org/EIPS/eip-721>`_. These are imported from ``ethereum.ercs``:

.. code-block:: vyper

    from ethereum.ercs import IERC20

    implements: IERC20

You can see all the available built-in interfaces in the `Vyper GitHub <https://github.com/vyperlang/vyper/tree/master/vyper/builtins/interfaces>`_ repo.

Implementing an Interface
=========================

You can define an interface for your contract with the ``implements`` statement:

.. code-block:: vyper

    import an_interface as FooBarInterface

    implements: FooBarInterface


This imports the defined interface from the vyper file at ``an_interface.vy`` (or ``an_interface.json`` if using ABI json interface type) and ensures your current contract implements all the necessary external functions. If any interface functions are not included in the contract, it will fail to compile. This is especially useful when developing contracts around well-defined standards such as ERC20.

.. note::

  Interfaces that implement functions with return values that require an upper bound (e.g. ``Bytes``, ``DynArray``, or ``String``), the upper bound defined in the interface represents the lower bound of the implementation. Assuming a function ``my_func`` returns a value ``String[1]`` in the interface, this would mean for the implementation function of ``my_func`` that the return value must have **at least** length 1. This behavior might change in the future.

Extracting Interfaces
=====================

Vyper has a built-in format option to allow you to make your own Vyper interfaces easily.

::

    $ vyper -f interface examples/voting/ballot.vy

    # Functions

    @view
    @external
    def delegated(addr: address) -> bool:
        pass

    # ...

If you want to do an external call to another contract, Vyper provides an external interface extract utility as well.

::

    $ vyper -f external_interface examples/voting/ballot.vy

    # External Contracts
    interface Ballot:
        def delegated(addr: address) -> bool: view
        def directlyVoted(addr: address) -> bool: view
        def giveRightToVote(voter: address): nonpayable
        def forwardWeight(delegate_with_weight_to_forward: address): nonpayable
        # ...

The output can then easily be copy-pasted to be consumed.

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
        extcall foobar.test1()

    @external
    def test2(foobar: FooBar) -> uint256:
        return staticcall foobar.calculate()

The interface name can also be used as a type annotation for storage variables. You then assign an address value to the variable to access that interface. Note that casting an address to an interface is possible, e.g. ``FooBar(<address_var>)``:

.. code-block:: vyper

    foobar_contract: FooBar

    @deploy
    def __init__(foobar_address: address):
        self.foobar_contract = FooBar(foobar_address)

    @external
    def test():
        extcall self.foobar_contract.test1()

Specifying ``payable`` or ``nonpayable`` annotation in the interface indicates that the call made to the external contract will be able to alter storage, whereas ``view`` and ``pure`` calls will use a ``STATICCALL`` ensuring no storage can be altered during execution. Additionally, ``payable`` allows non-zero value to be sent along with the call.

The ``extcall`` or ``staticcall`` keyword is required to precede the external call to distinguish it from internal calls. The keyword must match the visibility of the function, ``staticcall`` for ``pure`` and ``view`` functions, and ``extcall`` for ``payable`` and ``nonpayable`` functions. Additionally, the output of a ``staticcall`` must be assigned to a result.

.. code-block:: vyper

    interface FooBar:
        def calculate() -> uint256: pure
        def query() -> uint256: view
        def update(): nonpayable
        def pay(): payable

    @external
    def test(foobar: FooBar):
        s: uint256 = staticcall foobar.calculate()  # cannot change storage
        s = staticcall foobar.query()  # cannot change storage, but reads itself
        extcall foobar.update()  # storage can be altered
        extcall foobar.pay(value=1)  # storage can be altered, and value can be sent

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

    extcall IERC20(USDT).transfer(msg.sender, 1, default_return_value=True) # returns True
    extcall IERC20(USDT).transfer(msg.sender, 1) # reverts because nothing returned

.. warning::

   When ``skip_contract_check=True`` is used and the called function returns data (ex.: ``x: uint256 = SomeContract.foo(skip_contract_check=True)``, no guarantees are provided by the compiler as to the validity of the returned value. In other words, it is undefined behavior what happens if the called contract did not exist. In particular, the returned value might point to garbage memory. It is therefore recommended to only use ``skip_contract_check=True`` to call contracts which have been manually ensured to exist at the time of the call.

Importing Interfaces
====================

Interfaces are imported with ``import`` or ``from ... import`` statements.

Imported interfaces are written using a variant of standard Vyper syntax. The body of each function must be an ellipsis (``...``). Interface files must have a ``.vyi`` suffix.

.. code-block:: vyper
    # my_interface.vyi

    @external
    def test1():
        ...

    @external
    def calculate() -> uint256:
        ...

Imports via ``import``
----------------------

You may import interfaces (defined in ``.vyi`` files) via ``import`` statements. You may use plain or ``as`` variants.

.. code-block:: vyper

    # without an alias
    import my_package.foo

    # with an alias
    import my_package.foo as bar

Imports via ``from ... import``
-------------------------------

Using ``from`` you can perform both absolute and relative imports. You may optionally include an alias - if you do not, the name of the interface will be the same as the file.

.. code-block:: vyper

    # without an alias
    from my_package import foo

    # with an alias
    from my_package import foo as bar

Relative imports are possible by prepending dots to the contract name. A single leading dot indicates a relative import starting with the current package. Two leading dots indicate a relative import from the parent of the current package:

.. code-block:: vyper

    from . import foo
    from ..interfaces import baz


The concept of a package does not exist as a first-class construct in vyper as it does in python. That is, imports correspond 1:1 to files; you cannot import a directory which contains an ``__init__.vy`` file and get a module object which contains pointers to other modules.

.. _searching_for_imports:

Searching For Interface Files
-----------------------------

When looking for a file to import, Vyper will first search relative to the same folder as the contract being compiled. It then checks for the file in the provided search paths, in the precedence provided. Vyper checks for the file name with a ``.vy`` suffix first, then ``.vyi``, then ``.json``.

When using the command line compiler, the search path path defaults to the current working directory, plus the python `syspath <https://docs.python.org/3.11/library/sys.html#sys.path>_`. You can append to the search path with the ``-p`` flag:

::

    $ vyper my_project/contracts/my_contract.vy -p my_project

In the above example, the ``my_project`` folder is set as the root path.

You can additionally disable the behavior of adding the syspath to the search path with the CLI flag ``--disable-sys-path``:

::

    $ vyper --disable-sys-path my_project/my_contract.vy

Built-in Interfaces
===================

Vyper includes common built-in interfaces such as `IERC20 <https://eips.ethereum.org/EIPS/eip-20>`_ and `IERC721 <https://eips.ethereum.org/EIPS/eip-721>`_. These are imported from ``ethereum.ercs``:

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


This imports the defined interface from the vyper file at ``an_interface.vyi`` (or ``an_interface.json`` if using ABI json interface type) and ensures your current contract implements all the necessary external functions. If any interface functions are not included in the contract, it will fail to compile. This is especially useful when developing contracts around well-defined standards such as ERC20.

.. note::

  Interfaces that implement functions with return values that require an upper bound (e.g. ``Bytes``, ``DynArray``, or ``String``), the upper bound defined in the interface represents the lower bound of the implementation. Assuming a function ``my_func`` returns a value ``String[1]`` in the interface, this would mean for the implementation function of ``my_func`` that the return value must have **at least** length 1. This behavior might change in the future.

Extracting Interfaces
=====================

Vyper has a built-in format option to allow you to easily export a Vyper interface from a pre-existing contract.

::

    $ vyper -f interface examples/voting/ballot.vy

    # Functions

    @view
    @external
    def delegated(addr: address) -> bool:
        ...

    # ...

If you want to export it as an inline interface, Vyper provides a utility to extract that as well.

::

    $ vyper -f external_interface examples/voting/ballot.vy

    # External Contracts
    interface Ballot:
        def delegated(addr: address) -> bool: view
        def directlyVoted(addr: address) -> bool: view
        def giveRightToVote(voter: address): nonpayable
        def forwardWeight(delegate_with_weight_to_forward: address): nonpayable
        # ...

The output can then easily be copy-pasted directly in a regular vyper file.

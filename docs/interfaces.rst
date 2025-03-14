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

Either the ``extcall`` or ``staticcall`` keyword is required to precede the external call to distinguish it from internal calls. The keyword must match the visibility of the function, ``staticcall`` for ``pure`` and ``view`` functions, and ``extcall`` for ``payable`` and ``nonpayable`` functions. Additionally, the output of a ``staticcall`` must be assigned to a result.

.. warning::

    If the signature in an interface does not match the actual signature of the called contract, you can get runtime errors or undefined behavior. For instance, if you accidentally mark a ``nonpayable`` function as ``view``, calling that function may result in the EVM reverting execution in the called contract.

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

=============================== ==============================================================
Keyword                         Description
=============================== ==============================================================
``gas``                         Specify gas value for the call
``value``                       Specify amount of ether sent with the call
``skip_contract_check``         Drop ``EXTCODESIZE`` check (but keep ``RETURNDATASIZE`` check)
``default_return_value``        Specify a default return value if no value is returned
=============================== ==============================================================

The ``default_return_value`` parameter can be used to handle ERC20 tokens affected by the missing return value bug in a way similar to OpenZeppelin's ``safeTransfer`` for Solidity:

.. code-block:: vyper

    extcall IERC20(USDT).transfer(msg.sender, 1, default_return_value=True) # returns True
    extcall IERC20(USDT).transfer(msg.sender, 1) # reverts because nothing returned

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

.. note::

  Prior to v0.4.0, ``implements`` required that events defined in an interface were re-defined in the "implementing" contract. As of v0.4.0, this is no longer required because events can be used just by importing them. Any events used in a contract will automatically be exported in the ABI output.

.. note::

  An interface function with default parameters (e.g. ``deposit(assets: uint256, receiver: address = msg.sender)``) implies that the contract being interfaced with supports these default arguments via the ABI-encoded function signatures (e.g. ``keccak256("deposit(uint256,address)")[:4]`` and ``keccak256("deposit(uint256)")[:4]``). It is the responsibility of the callee to implement the behavior associated with these defaults.

Standalone Interfaces
=====================

Standalone interfaces are written using a variant of standard Vyper syntax. The body of each function must be an ellipsis (``...``). Interface files must have a ``.vyi`` suffix in order to be found by an import statement.

.. code-block:: vyper
    # ISomeInterface.vyi

    @external
    def test1():
        ...

    @external
    def calculate() -> uint256:
        ...

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

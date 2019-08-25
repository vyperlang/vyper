.. index:: contract, state variable, function, metadata;

.. _contract_structure:

Structure of a Contract
***********************

Contracts in Vyper are contained within files, with each file being one smart-contract.  Files in Vyper are similar to classes in object-oriented languages.
Each file can contain declarations of :ref:`structure-state-variables` and :ref:`structure-functions`.

.. _structure-state-variables:

State Variables
===============

State variables are values which are permanently stored in contract storage.

::

  storedData: int128

See the :ref:`types` section for valid state variable types.

.. _structure-functions:

Functions
=========

Functions are the executable units of code within a contract.

::

  @public
  @payable
  def bid(): // Function
    // ...

Function calls can happen internally or externally and have different levels of visibility (see
:ref:`structure-decorators`) towards other contracts. Functions must be explicitely declared as public or private.

Public Functions
----------------

Public functions (decorated with ``@public``) are a part of the contract interface and may be called via transactions or from other contracts. They cannot be called internally.

Public functions in Vyper are equivalent to external functions in Solidity.

Private Functions
-----------------

Private functions (decorated with ``@private``) are only accessible from other functions within the same contract. They are called via the ``self`` variable:

::

    @private
    def _times_two(amount: uint256) -> uint256:
        return amount * 2

    @public
    def calculate(amount: uint256) -> uint256:
        return self._times_two(amount)

Private functions do not have access to ``msg.sender`` or ``msg.value``. If you require these values within a private function they must be passed as parameters.

.. _structure-decorators:

Decorators
----------

The following decorators are available:

=============================== ===========================================
Decorator                       Description
=============================== ===========================================
``@public``                     Can only be called externally.
``@private``                    Can only be called within current contract.
``@constant``                   Does not alter contract state.
``@payable``                    The contract is open to receive Ether.
``@nonreentrant(<unique_key>)`` Function can only be called once,
                                both externally and internally. Used to
                                prevent reentrancy attacks.
=============================== ===========================================

The visibility decorators ``@public`` or ``@private`` are mandatory on function declarations, whilst the other decorators(``@constant``, ``@payable``, ``@nonreentrant``) are optional.

Default function
----------------

A contract can also have a default function, which is executed on a call to the contract if no other functions match the given function identifier (or if none was supplied at all, such as through someone sending it Eth). It is the same construct as fallback functions `in Solidity <https://solidity.readthedocs.io/en/latest/contracts.html?highlight=fallback#fallback-function>`_.

This function is always named `__default__` and must be annotated with `@public`. It cannot have arguments and cannot return anything.

If the function is annotated as `@payable`, this function is executed whenever the contract is sent Ether (without data). This is why the default function cannot accept arguments and return values - it is a design decision of Ethereum to make no differentiation between sending ether to a contract or a user address.

**Example:**

::

    Payment: event({amount: int128, from: indexed(address)})

    @public
    @payable
    def __default__():
        log.Payment(msg.value, msg.sender)

Considerations
~~~~~~~~~~~~~~

Just as in Solidity, Vyper generates a default function if one isn't found, in the form of a REVERT call. Note that this still `generates an exception <https://github.com/ethereum/wiki/wiki/Subtleties>`_ and thus will not succeed in receiving funds.

Ethereum specifies that the operations will be rolled back if the contract runs out of gas in execution. ``send`` calls to the contract come with a free stipend of 2300 gas, which does not leave much room to perform other operations except basic logging. **However**, if the sender includes a higher gas amount through a ``call`` instead of ``send``, then more complex functionality can be run.

It is considered a best practice to ensure your payable default function is compatible with this stipend. The following operations will consume more than 2300 gas:

- Writing to storage
- Creating a contract
- Calling an external function which consumes a large amount of gas
- Sending Ether

Lastly, although the default function receives no arguments, it can still access the ``msg`` global, including:

- the address of who is interacting with the contract (``msg.sender``)
- the amount of ETH sent (``msg.value``)
- the gas provided (``msg.gas``).

.. _structure-events:

Events
======

Events may be logged in specially indexed data structures that allow clients, including light clients, to efficiently search for them.

::

    Payment: event({amount: int128, arg2: indexed(address)})

    total_paid: int128

    @public
    @payable
    def pay():
        self.total_paid += msg.value
        log.Payment(msg.value, msg.sender)

Events must be declared before global declarations and function definitions.

.. structure-metadata:

NatSpec Metadata
================

Vyper supports structured documentation for state variables and functions and events.

::

  carrotsEaten: int128
  """
  @author Bob Clampett
  @notice Number of carrots eaten
  @dev Chewing does not count, carrots must pass the throat to be "eaten"
  """

::

  @public
  @payable
  def doesEat(food: string):
    """
    @author Bob Clampett
    @notice Determine if Bugs will accept `food` to eat
    @dev Compares the entire string and does not rely on a hash
    @param food The name of a food to evaluate (in English)
    @return true if Bugs will eat it, false otherwise
    """

    // ...

::

  Ate: event({food: string})
  """
  @author Bob Clampett
  @notice Bugs did eat `food`
  @dev Chewing does not count, carrots must pass the throat to be "eaten"
  @param food The name of a food that was eaten (in English)
  """

Additional information about Ethereum Natural Specification (NatSpec) can be found `here <https://github.com/ethereum/wiki/wiki/Ethereum-Natural-Specification-Format>`_.

Contract Interfaces
===================

An interface is a set of function definitions used to enable communication between smart contracts. A contract interface defines all of that contract's publicly available functions. By importing the interface, your contract now knows how to call these functions in other contracts.

Defining Interfaces and Making External Calls
---------------------------------------------

Interfaces can be added to contracts either through inline definition, or by importing them from a seperate file.

The ``contract`` keyword is used to define an inline external interface:

.. code-block:: python

    contract FooBar:
        def calculate() -> uint256: constant
        def test1(): modifying

The defined interface can then be use to make external calls, given a contract address:

.. code-block:: python

    @public
    def test(some_address: address):
        FooBar(some_address).calculate()

The interface name can also be used as a type annotation for storage variables. You then assign an address value to the variable to access that interface. Note that assignment of an address requires the value to be cast using the contract type e.g. ``FooBar(<address_var>)``:

.. code-block:: python

    foobar_contract: FooBar

    @public
    def __init__(foobar_address: address):
        self.foobar_contract = FooBar(foobar_address)

    @public
    def test():
        self.foobar_contract.calculate()

Specifying ``modifying`` annotation indicates that the call made to the external contract will be able to alter storage, whereas the ``constant`` call will use a ``STATICCALL`` ensuring no storage can be altered during execution.

::

    contract FooBar:
        def calculate() -> uint256: constant
        def test1(): modifying

    @public
    def test(some_address: address):
        FooBar(some_address).calculate()  # cannot change storage
        FooBar(some_address).test1()  # storage can be altered


Importing Interfaces
--------------------

Interfaces are imported with ``import`` or ``from ... import`` statements.

Imported interfaces are written using standard Vyper syntax, with the body of each function replaced by a ``pass`` statement:

.. code-block:: python

    @public
    def test1():
        pass

    @public
    def calculate() -> uint256:
        pass

You can also import a fully implemented contract and Vyper will automatically convert it to an interface.

Imports via ``import``
~~~~~~~~~~~~~~~~~~~~~~

With absolute ``import`` statements, you **must** include an alias as a name for the imported package. In the following example, failing to include ``as Foo`` will raise a compile error:

.. code-block:: python

    import contract.foo as Foo

Imports via ``from ... import``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Using ``from`` you can perform both absolute and relative imports. With ``from`` import statements you **cannot** use an alias - the name of the interface will always be that of the file:

.. code-block:: python

    from contract import foo

Relative imports are possible by prepending dots to the contract name. A single leading dot indicates a relative import starting with the current package. Two leading dots indicate a relative import from the parent of the current package:

.. code-block:: python

    from . import foo
    from ..interfaces import baz

Searching For Interface Files
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

When looking for a file to import Vyper will first search relative to the same folder as the contract being compiled. For absolute imports, it also searches relative to the root path for the project. Vyper checks for the file name with a ``.vy`` suffix first, then ``.json``.

When using the command line compiler, the root path defaults to to the current working directory. You can change it with the ``-p`` flag:

::

    $ vyper my_project/contracts/my_contract.vy -p my_project

In the above example, the ``my_project`` folder is set as the root path. A contract cannot perform a relative import that goes beyond the top-level folder.

Built-in Interfaces
-------------------

Vyper includes common built-in interfaces such as `ERC20 <https://eips.ethereum.org/EIPS/eip-20>`_ and `ERC721 <https://eips.ethereum.org/EIPS/eip-721>`_. These are imported from ``vyper.interfaces``:

.. code-block:: python

    from vyper.interfaces import ERC20

    implements: ERC20

You can see all the available built-in interfaces in the `Vyper GitHub <https://github.com/ethereum/vyper/tree/master/vyper/interfaces>`_ repo.


Implementing an Interface
-------------------------

You can define an interface for your contract with the ``implements`` statement:

.. code-block:: python

    import an_interface as FooBarInterface

    implements: FooBarInterface


This imports the defined interface from the vyper file at ``an_interface.vy`` (or ``an_interface.json`` if using ABI json interface type) and ensures your current contract implements all the necessary public functions. If any interface functions are not included in the contract, it will fail to compile. This is especially useful when developing contracts around well-defined standards such as ERC20.

Extracting Interfaces
---------------------

Vyper has a built-in format option to allow you to make your own vyper interfaces easily.

::

    $ vyper -f interface examples/voting/ballot.vy

    # Functions

    @constant
    @public
    def delegated(addr: address) -> bool:
        pass

    # ...

If you want to do an external call to another contract, vyper provides an external contract extract utility as well.

::

    $ vyper -f external_interface examples/voting/ballot.vy

    # External Contracts
    contract Ballot:
        def delegated(addr: address) -> bool: constant
        def directlyVoted(addr: address) -> bool: constant
        def giveRightToVote(voter: address): modifying
        def forwardWeight(delegate_with_weight_to_forward: address): modifying
        # ...

The output can then easily be copy-pasted to be consumed.

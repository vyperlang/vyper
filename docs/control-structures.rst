.. _control-structures:

Control Structures
##################

.. _control-structures-functions:

Functions
=========

Functions are executable units of code within a contract. Functions may only be declared within a contract's :ref:`module scope <scoping-module>`.

.. code-block:: vyper

    @external
    def bid():
        ...

Functions may be called internally or externally depending on their :ref:`visibility <function-visibility>`. Functions may accept input arguments and return variables in order to pass values between them.

Visibility
----------

.. _function-visibility:

You can optionally declare a function's visibility by using a :ref:`decorator <function-decorators>`. There are three visibility levels in Vyper:

    * ``@external``: exposed in the selector table, can be called by an external call into this contract
    * ``@internal`` (default): can be invoked only from within this contract. Not available to external callers
    * ``@deploy``: constructor code. This is code which is invoked once in the lifetime of a contract, upon its deploy. It is not available at runtime to either external callers or internal call invocations. At this time, only the :ref:`__init__() function <init-function>` may be marked as ``@deploy``.


External Functions
******************

External functions (marked with the ``@external`` decorator) are a part of the contract interface and may only be called via transactions or from other contracts.

.. code-block:: vyper

    @external
    def add_seven(a: int128) -> int128:
        return a + 7

    @external
    def add_seven_with_overloading(a: uint256, b: uint256 = 3):
        return a + b

A Vyper contract cannot call directly between two external functions. If you must do this, you can use an :ref:`interface <interfaces>`.

.. note::
    For external functions with default arguments like ``def my_function(x: uint256, b: uint256 = 1)`` the Vyper compiler will generate ``N+1`` overloaded function selectors based on ``N`` default arguments.

.. _structure-functions-internal:

Internal Functions
******************

Internal functions (optionally marked with the ``@internal`` decorator) are only accessible from other functions within the same contract. They are invoked via the :ref:`self<constants-self>` object:

.. code-block:: vyper

    def _times_two(amount: uint256) -> uint256:
        return amount * 2

    @external
    def calculate(amount: uint256) -> uint256:
        return self._times_two(amount)

Or for internal functions which are defined in :ref:`imported modules <modules>`, they are invoked by prefixing the name of the module to the function name:

.. code-block:: vyper
    import calculator_library

    @external
    def calculate(amount: uint256) -> uint256:
        return calculator_library._times_two(amount)

.. note::
   As of v0.4.0, the ``@internal`` decorator is optional. That is, functions with no visibility decorator default to being ``internal``.

.. note::
    Please note that for ``internal`` functions which use more than one default parameter, Vyper versions ``>=0.3.8`` are recommended due to the security advisory `GHSA-ph9x-4vc9-m39g <https://github.com/vyperlang/vyper/security/advisories/GHSA-ph9x-4vc9-m39g>`_.


The ``__init__`` Function
-------------------------

.. _init-function:

The ``__init__()`` function, also known as the constructor, is a special initialization function that is only called at the time of deploying a contract. It can be used to set initial values for storage or immutable variables. It must be declared with the ``@deploy`` decorator. A common use case is to set an ``owner`` variable with the creator of the contract:

.. code-block:: vyper

    owner: address

    @deploy
    def __init__():
        self.owner = msg.sender

Additionally, :ref:`immutable variables <immutable-variables>` may only be set within the constructor.


Mutability
----------

.. _function-mutability:

You can optionally declare a function's mutability by using a :ref:`decorator <function-decorators>`. There are four mutability levels:

    * ``@pure``: does not read from the contract state or any environment variables.
    * ``@view``: may read from the contract state, but does not alter it.
    * ``@nonpayable`` (default): may read from and write to the contract state, but cannot receive Ether.
    * ``@payable``: may read from and write to the contract state, and can receive Ether.

.. code-block:: vyper

    @view
    @external
    def readonly():
        # this function cannot write to state
        ...

    @payable
    @external
    def send_me_money():
        # this function can receive ether
        ...

Functions default to ``nonpayable`` when no mutability decorator is used.

Functions marked with ``@view`` cannot call mutable (``payable`` or ``nonpayable``) functions. Any external calls are made using the special ``STATICCALL`` opcode, which prevents state changes at the EVM level.

Functions marked with ``@pure`` cannot call non-``pure`` functions.

Re-entrancy Locks
-----------------

The ``@nonreentrant`` decorator places a global nonreentrancy lock on a function. An attempt by an external contract to call back into any other ``@nonreentrant`` function causes the transaction to revert.

.. code-block:: vyper

    @external
    @nonreentrant
    def make_a_call(_addr: address):
        # this function is protected from re-entrancy
        ...

You can put the ``@nonreentrant`` decorator on a ``__default__`` function but we recommend against it because in most circumstances it will not work in a meaningful way.

Nonreentrancy locks work by setting a specially allocated storage slot to a ``<locked>`` value on function entrance, and setting it to an ``<unlocked>`` value on function exit. On function entrance, if the storage slot is detected to be the ``<locked>`` value, execution reverts.

You cannot put the ``@nonreentrant`` decorator on a ``pure`` function. You can put it on a ``view`` function, but it only checks that the function is not in a callback (the storage slot is not in the ``<locked>`` state), as ``view`` functions can only read the state, not change it.

You can view where the nonreentrant key is physically laid out in storage by using ``vyper`` with the ``-f layout`` option (e.g., ``vyper -f layout foo.vy``). Unless it is overridden, the compiler will allocate it at slot ``0``.

.. note::
    A mutable function can protect a ``view`` function from being called back into (which is useful for instance, if a ``view`` function would return inconsistent state during a mutable function), but a ``view`` function cannot protect itself from being called back into. Note that mutable functions can never be called from a ``view`` function because all external calls out from a ``view`` function are protected by the use of the ``STATICCALL`` opcode.

.. note::

    A nonreentrant lock has an ``<unlocked>`` value of 3, and a ``<locked>`` value of 2. Nonzero values are used to take advantage of net gas metering - as of the Berlin hard fork, the net cost for utilizing a nonreentrant lock is 2300 gas. Prior to v0.3.4, the ``<unlocked>`` and ``<locked>`` values were 0 and 1, respectively.

.. note::
   Prior to 0.4.0, nonreentrancy keys took a "key" argument for fine-grained nonreentrancy control. As of 0.4.0, only a global nonreentrancy lock is available.

The ``__default__`` Function
----------------------------

A contract can also have a default function, which is executed on a call to the contract if no other functions match the given function identifier (or if none was supplied at all, such as through someone sending it Eth). It is the same construct as fallback functions `in Solidity <https://solidity.readthedocs.io/en/latest/contracts.html?highlight=fallback#fallback-function>`_.

This function is always named ``__default__``. It must be annotated with ``@external``. It cannot expect any input arguments.

If the function is annotated as ``@payable``, this function is executed whenever the contract is sent Ether (without data). This is why the default function cannot accept arguments - it is a design decision of Ethereum to make no differentiation between sending ether to a contract or a user address.

.. code-block:: vyper

    event Payment:
        amount: uint256
        sender: indexed(address)

    @external
    @payable
    def __default__():
        log Payment(msg.value, msg.sender)

Considerations
**************

Just as in Solidity, Vyper generates a default function if one isn't found, in the form of a ``REVERT`` call. Note that this rolls back state changes, and thus will not succeed in receiving funds.

Ethereum specifies that the operations will be rolled back if the contract runs out of gas in execution. ``send`` calls to the contract come with a free stipend of 2300 gas, which does not leave much room to perform other operations except basic logging. **However**, if the sender includes a higher gas amount through a ``call`` instead of ``send``, then more complex functionality can be run.

It is considered a best practice to ensure your payable default function is compatible with this stipend. The following operations will consume more than 2300 gas:

    * Writing to storage
    * Creating a contract
    * Calling an external function which consumes a large amount of gas
    * Sending Ether

Lastly, although the default function receives no arguments, it can still access the ``msg`` object, including:

    * the address of who is interacting with the contract (``msg.sender``)
    * the amount of ETH sent (``msg.value``)
    * the gas provided (``msg.gas``).

.. _function-decorators:

Decorators Reference
--------------------

=============================== ===========================================================
Decorator                       Description
=============================== ===========================================================
``@external``                   Function can only be called externally, it is part of the runtime selector table
``@internal``                   Function can only be called within current contract
``@deploy``                     Function is called only at deploy time
``@pure``                       Function does not read contract state or environment variables
``@view``                       Function does not alter contract state
``@payable``                    Function is able to receive Ether
``@nonreentrant``               Function cannot be called back into during an external call
=============================== ===========================================================

``if`` statements
=================

The ``if`` statement is a control flow construct used for conditional execution:

.. code-block:: vyper

    if CONDITION:
        ...

``CONDITION`` is a boolean or boolean operation. The boolean is evaluated left-to-right, one expression at a time, until the condition is found to be true or false.  If true, the logic in the body of the ``if`` statement is executed.

Note that unlike Python, Vyper does not allow implicit conversion from non-boolean types within the condition of an ``if`` statement. ``if 1: pass`` will fail to compile with a type mismatch.

You can also include ``elif`` and ``else`` statements, to add more conditional statements and a body that executes when the conditionals are false:

.. code-block:: vyper

    if CONDITION:
        ...
    elif OTHER_CONDITION:
        ...
    else:
        ...

``for`` loops
=============

The ``for`` statement is a control flow construct used to iterate over a value:

.. code-block:: vyper

    for i: <TYPE> in <ITERABLE>:
        ...

The iterated value can be a static array, a dynamic array, or generated from the built-in ``range`` function.

Array Iteration
---------------

You can use ``for`` to iterate through the values of any array variable:

.. code-block:: vyper

    foo: int128[3] = [4, 23, 42]
    for i: int128 in foo:
        ...

In the above, example, the loop executes three times with ``i`` assigned the values of ``4``, ``23``, and then ``42``.

You can also iterate over a literal array, as long as the annotated type is valid for each item in the array:

.. code-block:: vyper

    for i: int128 in [4, 23, 42]:
        ...

Some restrictions:

* You cannot iterate over a multi-dimensional array.  ``i`` must always be a base type.
* You cannot modify a value in an array while it is being iterated, or call to a function that might modify the array being iterated.

Range Iteration
---------------

Ranges are created using the ``range`` function. The following examples are valid uses of ``range``:

.. code-block:: vyper

    for i: uint256 in range(STOP):
        ...

``STOP`` is a literal integer greater than zero. ``i`` begins as zero and increments by one until it is equal to ``STOP``. ``i`` must be of the same type as ``STOP``.

.. code-block:: vyper

    for i: uint256 in range(stop, bound=N):
        ...

Here, ``stop`` can be a variable with integer type, greater than zero. ``N`` must be a compile-time constant. ``i`` begins as zero and increments by one until it is equal to ``stop``. If ``stop`` is larger than ``N``, execution will revert at runtime. In certain cases, you may not have a guarantee that ``stop`` is less than ``N``, but still want to avoid the possibility of runtime reversion. To accomplish this, use the ``bound=`` keyword in combination with ``min(stop, N)`` as the argument to ``range``, like ``range(min(stop, N), bound=N)``. This is helpful for use cases like chunking up operations on larger arrays across multiple transactions. ``i``, ``stop`` and ``N`` must be of the same type.

Another use of range can be with ``START`` and ``STOP`` bounds.

.. code-block:: vyper

    for i: uint256 in range(START, STOP):
        ...

Here, ``START`` and ``STOP`` are literal integers, with ``STOP`` being a greater value than ``START``. ``i`` begins as ``START`` and increments by one until it is equal to ``STOP``. ``i``, ``START`` and ``STOP`` must be of the same type.

Finally, it is possible to use ``range`` with runtime `start` and `stop` values as long as a constant `bound` value is provided.
In this case, Vyper checks at runtime that `end - start <= bound`.
``N`` must be a compile-time constant. ``i``, ``stop`` and ``N`` must be of the same type.

.. code-block:: vyper

    for i: uint256 in range(start, end, bound=N):
        ...

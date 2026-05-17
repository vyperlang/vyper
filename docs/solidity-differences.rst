.. _solidity-differences:

Differences from Solidity
#########################

This page covers the key differences between Solidity and Vyper, the reasoning behind them, and their consequences.

Quick Reference
===============

.. list-table::
   :header-rows: 1
   :widths: 30 35 35

   * - Solidity
     - Vyper
     - Rationale
   * - ``modifier``
     - Inline checks
     - Control flow is explicit in the function body
   * - ``class inheritance``
     - ``import`` + ``exports``
     - Explicit dependencies
   * - ``assembly { }``
     - Not supported
     - No direct EVM opcode access; use specific builtins (``raw_call``, ``create_minimal_proxy_to``, etc.)
   * - ``while (true)``
     - ``for i in range(n)``
     - Bounded gas costs
   * - ``mapping``
     - ``HashMap``
     - Same semantics
   * - ``emit Event()``
     - ``log Event()``
     - Same semantics
   * - ``require()``
     - ``assert`` / ``raise``
     - Different semantics; explicit error paths
   * - ``contract.call()``
     - ``extcall`` / ``staticcall``
     - Explicit external calls

Philosophy
==========

Vyper prioritizes three properties: security, simplicity, and auditability.

To achieve these properties, Vyper excludes features that obscure control flow or make code difficult to reason about. Each omission is a deliberate tradeoff: less flexibility in exchange for explicit behavior. See :ref:`Principles <design-principles>` for the full rationale.

No Modifiers
============

Solidity modifiers wrap function execution:

.. code-block:: solidity

    modifier onlyOwner() {
        require(msg.sender == owner, "Not owner");
        _;
    }

    function withdraw() public onlyOwner {
        // ...
    }

While ``onlyOwner`` appears simple, modifiers can execute code before and after the function body, modify state, and obscure the actual logic. Understanding a function requires reading the modifier definitions elsewhere in the codebase. For this reason, Vyper does not have modifiers.

In Vyper, checks are written inline:

.. code-block:: vyper

    @external
    def withdraw():
        assert msg.sender == self.owner, "Not owner"
        # ...

Inline checks keep the control flow visible from top to bottom.

No Class Inheritance
====================

Solidity supports multiple inheritance, which introduces the diamond problem and C3 linearization complexity. Vyper excludes inheritance entirely.

In Vyper 0.4.0, a module system was introduced for powerful code reuse:

.. code-block:: vyper

    import ownable

    initializes: ownable
    exports: ownable.transfer_ownership

    @deploy
    def __init__():
        ownable.__init__()

Three declarations manage module relationships: ``initializes`` (this contract manages the module's storage), ``uses`` (this contract reads module state without initializing), and ``exports`` (expose module functions in the ABI). See :doc:`using-modules` for details.

A contract can be understood by reading one file and its direct imports; dependencies and what is exposed in the external function table are explicit.

No Inline Assembly
==================

Vyper excludes inline assembly. For low-level operations, use the :ref:`built-in functions <built_in_functions>`: ``raw_call``, ``raw_create``, ``create_minimal_proxy_to``, ``create_from_blueprint``.

Assembly bypasses compiler safety checks: type verification, overflow protection, memory safety, and requires reviewers to reason about raw opcodes. Vyper's built-in functions provide low-level access through explicit, auditable function calls.

No Function Overloading
=======================

Solidity permits multiple functions with the same name and different parameters:

.. code-block:: solidity

    function transfer(address to, uint256 amount) public { }
    function transfer(address to, uint256 amount, bytes data) public { }

Vyper requires unique function names, keeping the ABI and call sites explicit during review.

No Operator Overloading
=======================

``a + b`` always performs arithmetic addition. Operators cannot be redefined for custom types, so operator behavior is consistent across the codebase.

No Infinite Loops
=================

Vyper requires all loops to have a compile-time upper bound:

.. code-block:: vyper

    for i: uint256 in range(100):
        # Loop body

    # Variable count, but capped at compile time
    for i: uint256 in range(count, bound=100):
        # Loop body

Unbounded storage iteration can exceed the block gas limit, making contracts unusable. Bounded loops prevent this class of issue.

.. note::

   Vyper's bounded loops and lack of recursion make gas costs statically analyzable—every function call has a calculable upper bound (see :ref:`design-principles`).

No Recursion
============

Functions cannot call themselves, directly or through intermediate functions. Recursive logic must be converted to bounded iteration.

This constraint keeps the call graph acyclic and analyzable at compile time.

Bounded Dynamic Arrays
======================

Storage arrays require a maximum size at compile time:

.. code-block:: vyper

    balances: DynArray[uint256, 100]

This keeps gas costs predictable and can prevent denial-of-service attacks. For unbounded collections, use :ref:`HashMap <types>`.


Explicit Type Conversions
=========================

Vyper requires explicit type conversions:

.. code-block:: vyper

    x: uint256 = 100
    y: int256 = convert(x, int256)

    addr: address = 0x1234...
    num: uint160 = convert(addr, uint160)

Vyper allows safe automatic widening (e.g., ``uint8`` to ``uint256``) but requires explicit ``convert()`` for potentially lossy or semantically significant conversions, such as signed/unsigned, addresses to integers, or narrowing types. See :ref:`types` for the complete type reference.

Decimal Type
============

Native base-10 fixed-point arithmetic with 10 fractional digits:

.. code-block:: vyper

    a: decimal = 0.1
    b: decimal = 0.2
    total: decimal = a + b  # exactly 0.3

Values like ``0.1`` and ``0.2`` cannot be represented exactly in binary floating point, but Vyper's base-10 decimal type handles them precisely.

Solidity lacks a native fixed-point type, requiring manual integer scaling.

Bounds Checking
===============

Array accesses and arithmetic are bounds-checked at runtime. Out-of-bounds access reverts. Integer overflow reverts.

Solidity 0.8+ provides similar overflow protection, which is disabled in ``unchecked`` blocks. In Vyper, there is no way to disable the checks. For cases where wrapping behavior is needed, there are explicit :ref:`unsafe_* builtins <built_in_functions>`.

Reentrancy Protection
=====================

Built-in ``@nonreentrant`` decorator:

.. code-block:: vyper

    @external
    @nonreentrant
    def withdraw():
        # Cannot be re-entered

The compiler generates the mutex. No manual reentrancy guard implementation required.

.. note::

   The 2016 DAO hack exploited reentrancy to drain ~$60M in ETH. This led to the Ethereum hard fork that created Ethereum Classic.

The ``extcall`` keyword makes external call sites explicit and easy to spot during code review. Note that ``@nonreentrant`` is opt-in and uses a global lock that protects against same-contract reentrancy: if any ``@nonreentrant`` function is executing, no other ``@nonreentrant`` function in the same contract can be entered.

Alternatively, ``#pragma nonreentrancy`` enables reentrancy protection by default for all functions in the contract, so ``@nonreentrant`` is only needed when not using the pragma. It does not prevent cross-contract reentrancy (i.e., contract A calling contract B which calls back into contract A). See :ref:`control-structures` for details on the lock behavior.

Syntax Differences
==================

Practical syntax translations for common patterns.

.. note::

   Every Vyper file must start with a version pragma: ``#pragma version ^0.4.0``. This is similar to Solidity's ``pragma solidity ^0.8.0;`` but uses a comment syntax. Vyper files use the ``.vy`` extension.

State Variables
---------------

Solidity:

.. code-block:: solidity

    uint256 public counter;
    address private owner;

Vyper:

.. code-block:: vyper

    counter: public(uint256)
    owner: address

Variables are private by default. Use ``public()`` to generate a getter.

Functions
---------

Solidity:

.. code-block:: solidity

    function deposit() external payable returns (uint256) {
        return msg.value;
    }

Vyper:

.. code-block:: vyper

    @external
    @payable
    def deposit() -> uint256:
        return msg.value

Decorators specify visibility (``@external``, ``@internal``) and mutability (``@payable``, ``@view``, ``@pure``).

Constructor
-----------

Solidity:

.. code-block:: solidity

    constructor(address _owner) {
        owner = _owner;
    }

Vyper:

.. code-block:: vyper

    @deploy
    def __init__(owner: address):
        self.owner = owner

The ``@deploy`` decorator marks the constructor.

Events
------

Solidity:

.. code-block:: solidity

    event Transfer(address indexed from, address indexed to, uint256 value);

    function _transfer(address to, uint256 amount) internal {
        emit Transfer(msg.sender, to, amount);
    }

Vyper:

.. code-block:: vyper

    event Transfer:
        sender: indexed(address)
        receiver: indexed(address)
        amount: uint256

    @internal
    def _transfer(to: address, amount: uint256):
        log Transfer(msg.sender, to, amount)

``log`` instead of ``emit``.

Mappings
--------

Solidity:

.. code-block:: solidity

    mapping(address => uint256) public balances;
    mapping(address => mapping(address => uint256)) public allowances;

Vyper:

.. code-block:: vyper

    balances: public(HashMap[address, uint256])
    allowances: public(HashMap[address, HashMap[address, uint256]])

Interfaces
----------

Solidity:

.. code-block:: solidity

    interface IERC20 {
        function transfer(address to, uint256 amount) external returns (bool);
    }

Vyper (inline declaration):

.. code-block:: vyper

    interface IERC20:
        def transfer(to: address, amount: uint256) -> bool: nonpayable

Interfaces can also be defined in separate ``.vyi`` files (see :ref:`interfaces`). Vyper ships with built-in interfaces for ERC20, ERC721, etc. via ``from ethereum.ercs import IERC20``.

Error Handling
--------------

Solidity:

.. code-block:: solidity

    require(amount > 0, "Amount must be positive");
    revert("Operation failed");

Vyper:

.. code-block:: vyper

    assert amount > 0, "Amount must be positive"
    raise "Operation failed"

``assert`` for conditions, ``raise`` to revert.

Self Reference
--------------

State variables require ``self.`` prefix:

.. code-block:: vyper

    self.counter = self.counter + 1

Storage access is always explicit. Since storage operations cost more gas than memory operations, this distinction surfaces gas-intensive operations during review.

External Calls
--------------

Solidity:

.. code-block:: solidity

    IERC20(token).transfer(to, amount);
    uint256 balance = IERC20(token).balanceOf(address(this));

Vyper:

.. code-block:: vyper

    extcall IERC20(token).transfer(to, amount)
    balance: uint256 = staticcall IERC20(token).balanceOf(self)

``extcall`` for state-changing calls, ``staticcall`` for view/pure functions. The keywords make external calls and potential reentrancy points visible in code.

.. note::

   The ``extcall`` keyword is required for all state-changing external calls. There is no implicit external call syntax in Vyper: every external call is syntactically marked.

Structs
-------

Solidity:

.. code-block:: solidity

    struct Person {
        string name;
        uint256 age;
    }

    Person public owner;

Vyper:

.. code-block:: vyper

    struct Person:
        name: String[64]
        age: uint256

    owner: public(Person)

Note that Vyper strings require explicit maximum length (``String[64]``).

Constants and Immutables
------------------------

Solidity:

.. code-block:: solidity

    uint256 constant FEE = 100;
    address immutable owner;

    constructor() {
        owner = msg.sender;
    }

Vyper:

.. code-block:: vyper

    FEE: constant(uint256) = 100
    owner: immutable(address)

    @deploy
    def __init__():
        owner = msg.sender

``constant`` values are inlined at compile time. ``immutable`` values are set once during deployment and cannot be changed.

Default Function
----------------

Solidity:

.. code-block:: solidity

    fallback() external payable { }
    receive() external payable { }

Vyper:

.. code-block:: vyper

    @external
    @payable
    def __default__():
        pass

Vyper uses a single ``__default__`` function for both fallback and receive. It executes when no other function matches or when receiving plain ETH.

Why Vyper?
==========

Use Vyper if:

- **You have Python experience.** The syntax is familiar.
- **You want compiler-enforced constraints.** The compiler rejects unbounded loops, implicit conversions, and recursive calls.
- **You prefer explicit code.** One way to do most things. No modifiers, no inheritance, no operator overloading.
- **You want no global opt-out for safety checks.** Overflow and bounds checks can only be bypassed per-operation via ``unsafe_*`` builtins.

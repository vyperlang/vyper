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
     - ``raw_call()`` built-in
     - Low-level access via explicit built-ins
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

To achieve these properties, Vyper excludes features that obscure control flow or make code difficult to reason about. Each omission is a deliberate tradeoff: less flexibility in exchange for explicit behavior. See :ref:`Principles and Goals <design-principles>` for the full rationale.

.. note::

   Curve Finance chose Vyper for its AMM contracts because, in their view, developer errors are more likely than compiler errors. Vyper's restricted feature set reduces the surface area for such mistakes.

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

Vyper excludes modifiers. While ``onlyOwner`` appears simple, modifiers can execute code before and after the function body, modify state, and obscure the actual logic. Understanding a function requires reading the modifier definitions elsewhere in the codebase.

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

For code reuse, Vyper 0.4.0 introduced a module system:

.. code-block:: vyper

    import ownable

    initializes: ownable
    exports: ownable.transfer_ownership

    @deploy
    def __init__():
        ownable.__init__()

Three declarations manage module relationships: ``initializes`` (this contract manages the module's storage), ``uses`` (this contract reads module state without initializing), and ``exports`` (expose module functions in the ABI).

A contract can be understood by reading one file and its direct imports, and dependencies are explicit.

No Inline Assembly
==================

Vyper excludes inline assembly. For low-level operations, use the built-in functions: ``raw_call``, ``create_minimal_proxy_to``, ``create_from_blueprint``.

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

Every function has a calculable maximum gas cost. Unbounded storage iteration can exceed the block gas limit, making contracts unusable. Bounded loops prevent this class of issue.

.. note::

   Vyper's bounded loops and lack of recursion make gas costs statically analyzable. The official documentation states: "It is possible to compute a precise upper bound for the gas consumption of any Vyper function call.

No Recursion
============

Functions cannot call themselves, directly or through intermediate functions. Recursive logic must be converted to bounded iteration.

This constraint keeps the call graph acyclic and analyzable at compile time.

Bounded Dynamic Arrays
======================

Storage arrays require a maximum size at compile time:

.. code-block:: vyper

    balances: DynArray[uint256, 100]

Gas costs remain predictable, and attackers cannot grow arrays until iteration exceeds the block limit. For unbounded collections, use ``HashMap``.


Explicit Type Conversions
=========================

Vyper requires explicit type conversions:

.. code-block:: vyper

    x: uint256 = 100
    y: int256 = convert(x, int256)

    addr: address = 0x1234...
    num: uint160 = convert(addr, uint160)

Conversions between signed/unsigned integers or addresses and integers are visible in the code. No implicit casts that might hide bugs.

Decimal Type
============

Native fixed-point arithmetic with 10 decimal places:

.. code-block:: vyper

    price: decimal = 1.5
    quantity: decimal = 2.0
    total: decimal = price * quantity  # 3.0

Solidity lacks a native fixed-point type, requiring manual integer scaling.

Bounds Checking
===============

Array accesses and arithmetic are bounds-checked. Out-of-bounds access reverts. Integer overflow reverts.

Solidity 0.8+ provides similar overflow protection, but it can be disabled with ``unchecked`` blocks. Vyper keeps checks on by default; opt-out requires explicit ``unsafe_*`` builtins.

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

   The 2016 DAO hack exploited reentrancy to drain ~$60M in ETH (worth ~$150M at the time). This led to the Ethereum hard fork that created Ethereum Classic.

The ``@nonreentrant`` decorator, combined with the ``extcall`` keyword, makes reentrancy points visible during review. Note that ``@nonreentrant`` is opt-in and does not prevent all reentrancy patterns (e.g., cross-contract reentrancy).

Syntax Differences
==================

Practical syntax translations for common patterns.

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

The ``@deploy`` decorator marks the constructor (added in 0.4.0).

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

Vyper:

.. code-block:: vyper

    interface IERC20:
        def transfer(to: address, amount: uint256) -> bool: nonpayable

Interface files use ``.vyi`` extension. Vyper ships with built-in interfaces for ERC20, ERC721, etc. via ``from ethereum.ercs import IERC20``.

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

Why Vyper?
==========

Use Vyper if:

- **You have Python experience.** The syntax is familiar.
- **You want compiler-enforced constraints.** The compiler rejects unbounded loops, implicit conversions, and missing reentrancy guards.
- **You prefer explicit code.** One way to do most things. No modifiers, no inheritance, no operator overloading.
- **You want safety checks on by default.** Overflow protection and bounds checking require explicit opt-out via ``unsafe_*`` builtins.


Further Reading
===============

- :ref:`Types <types>` : Type system reference
- :ref:`Control Structures <control-structures>` : Loops, conditionals, functions
- :ref:`Interfaces <interfaces>` : Working with external contracts

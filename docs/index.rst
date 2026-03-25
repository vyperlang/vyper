.. image:: logo.svg
    :width: 140px
    :alt: Vyper logo
    :align: center

Vyper
#####

Vyper is a Pythonic smart contract language that compiles to `Ethereum Virtual Machine (EVM) <https://ethereum.org/learn/#ethereum-basics>`_ bytecode.
It prioritises **security**, **auditability**, and **simplicity**.

.. _design-principles:

Principles
==========

* **Security**: Building secure smart contracts should be natural, not an uphill battle.
* **Simplicity**: Both the language and compiler should be easy to understand.
* **Auditability**: Code should be maximally human-readable. Simplicity for the reader matters more than convenience for the writer.

Key Features
============

**Safety by default**

* Bounds and overflow checking on array accesses and arithmetic
* Reentrancy protection via the ``@nonreentrant`` decorator (see :ref:`control-structures`)
* Strong typing with explicit :ref:`type conversions <type_conversions>`

**Predictable execution**

* Decidable gas consumption: every function call has a calculable upper bound
* Bounded loops only (compile-time maximum iterations)
* No recursion: execution flow is structurally decreasing

**Clean code reuse**

* :ref:`Module imports <modules>` instead of class inheritance
* Explicit ``extcall`` and ``staticcall`` keywords for external contract interactions
* Support for :ref:`pure functions <function-mutability>` that cannot modify state

Compiler-Enforced Security
==========================

Vyper eliminates entire vulnerability classes by excluding features that enable dangerous patterns:

.. list-table::
   :header-rows: 1
   :widths: 25 75

   * - Excluded Feature
     - Why It Matters
   * - Inline assembly
     - Preserves type safety, overflow protection, and searchability of variable usage
   * - Class inheritance
     - Removes ambiguity about which code executes and simplifies auditing
   * - Modifiers
     - All checks are inline and visible, no hidden pre/post conditions
   * - Function overloading
     - Function calls are unambiguous; ``foo(x)`` always means the same thing
   * - Operator overloading
     - Arithmetic operators do exactly what they appear to do
   * - Infinite loops
     - Gas costs are always bounded and predictable
   * - Recursive calls
     - Call graphs are simple and gas limits are enforceable

These constraints mean developers cannot accidentally introduce dangerous patterns, even under time pressure or with limited blockchain experience.

Decimal Fixed Point
===================

Vyper uses decimal (not binary) fixed point numbers. This ensures that literals like ``0.1`` have exact representations, avoiding the subtle precision errors common in binary floating-point arithmetic.

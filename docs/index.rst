.. image:: logo.svg
    :width: 140px
    :alt: Vyper logo
    :align: center

Vyper
#####

Vyper is a contract-oriented, pythonic programming language that targets the `Ethereum Virtual Machine (EVM) <https://ethereum.org/learn/#ethereum-basics>`_.

Principles and Goals
====================

* **Security**: It should be possible and natural to build secure smart-contracts in Vyper.
* **Language and compiler simplicity**: The language and the compiler implementation should strive to be simple.
* **Auditability**: Vyper code should be maximally human-readable. Furthermore, it should be maximally difficult to write misleading code. Simplicity for the reader is more important than simplicity for the writer, and simplicity for readers with low prior experience with Vyper (and low prior experience with programming in general) is particularly important.

Because of this Vyper provides the following features:

* **Bounds and overflow checking**: On array accesses and arithmetic.
* **Support for signed integers and decimal fixed point numbers**
* **Decidability**: It is possible to compute a precise upper bound for the gas consumption of any Vyper function call.
* **Strong typing**
* **Clean and understandable compiler code**
* **Support for pure functions**: Anything marked ``pure`` is not allowed to change the state.
* **Code reuse through composition**: Vyper supports code reuse through composition, and to help auditors, requires syntactic marking of dependencies which potentially modify state.

Following the principles and goals, Vyper **does not** provide the following features:

* **Modifiers**: For example in Solidity you can define a ``function foo() mod1 { ... }``, where ``mod1`` can be defined elsewhere in the code to include a check that is done before execution, a check that is done after execution, some state changes, or possibly other things. Vyper does not have this, because it makes it too easy to write misleading code. ``mod1`` just looks too innocuous for something that could add arbitrary pre-conditions, post-conditions or state changes. Also, it encourages people to write code where the execution jumps around the file, harming auditability. The usual use case for a modifier is something that performs a single check before execution of a program; our recommendation is to simply inline these checks as asserts.
* **Class inheritance**: Class inheritance requires readers to jump between multiple files to understand what a program is doing, and requires readers to understand the rules of precedence in case of conflicts ("Which class's function ``X`` is the one that's actually used?").
* **Inline assembly**: Adding inline assembly would make it no longer possible to search for a variable name in order to find all instances where that variable is read or modified.
* **Function overloading**: This can cause lots of confusion on which function is called at any given time. Thus it's easier to write misleading code (``foo("hello")`` logs "hello" but ``foo("hello", "world")`` steals your funds). Another problem with function overloading is that it makes the code much harder to search through as you have to keep track on which call refers to which function.
* **Operator overloading**: Operator overloading makes writing misleading code possible. For example ``+`` could be overloaded so that it executes commands that are not visible at a first glance, such as sending funds the user did not want to send.
* **Recursive calling**: Recursive calling makes it impossible to set an upper bound on gas limits, opening the door for gas limit attacks.
* **Infinite-length loops**: Similar to recursive calling, infinite-length loops make it impossible to set an upper bound on gas limits, opening the door for gas limit attacks.
* **Binary fixed point**: Decimal fixed point is better, because any decimal fixed point value written as a literal in code has an exact representation, whereas with binary fixed point approximations are often required (e.g. (0.2)\ :sub:`10` = (0.001100110011...)\ :sub:`2`, which needs to be truncated), leading to unintuitive results, e.g. in Python 0.3 + 0.3 + 0.3 + 0.1 != 1.

Vyper **does not** strive to be a 100% replacement for everything that can be done in Solidity; it will deliberately forbid things or make things harder if it deems fit to do so for the goal of increasing security.

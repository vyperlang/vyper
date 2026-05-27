.. _vyper-deep-verification:

##################
Deep Verification
##################

Formal verification is becoming substantially more practical for smart contracts. Better tooling and accessible machine-checked semantics now make it feasible to prove properties on production code that were previously out of reach.

However, formal verification only proves that a program satisfies a specified property *within its formal model*. In practice, most verification work today establishes that property at only one layer of the stack. Everything else (from the accuracy and completeness of the model itself, through the compiler, to the EVM execution semantics), is taken on trust.

This distance between what is formally proved and what actually executes on chain is the **verification gap**.

**Deep verification** is the discipline of reducing that gap by formally bridging as many layers as possible. The fewer unverified assumptions remain in the chain, the stronger the resulting guarantee.

Verification Depth and Breadth
==============================

Two concepts help clarify the verification gap:

* **Verification depth** — how far the proof carries through the stack, from a high-level security property through source semantics and compiler correctness down to the EVM execution model.
* **Verification breadth** — how much of the contract’s actual behavior is covered: which functions, which properties, which sequences of operations, and which environment assumptions.

Every verification effort has some gap. Deep verification is the discipline of reducing it to its irreducible minimum.

The Layers
==========

::

        High-level properties
                │
                ▼
          Source semantics
                │
                ▼
         Compiler correctness
                │
                ▼
           EVM semantics
                │
                ▼
          Deployed bytecode

A source-level proof establishes a property under the language’s formal semantics. A bytecode-level proof establishes the analogous statement against a formal EVM model. A verified compiler connects the two. The fewer layers a guarantee skips by assumption, the smaller the verification gap.

The Technical Foundation
========================

Two of those layers already exist as public, machine-checked artifacts developed in the Verifereum project using HOL4:

* A formal semantics for the Vyper source language.
* A formal semantics for the EVM.

Together they provide the mathematical foundation against which source-level and bytecode-level proofs about Vyper programs can be stated. The work is fully open and available in the `vyper-hol <https://github.com/verifereum/vyper-hol>`_ repository.

Current Status
==============

Source-level verification on Vyper contracts and libraries is available today. Compiler verification (the critical link that connects source semantics to deployed bytecode) is in active development, with substantial proof engineering already underway.

No complete deep verification pipeline exists yet for any widely deployed smart-contract language. Vyper is one of the places where the pieces are actively being assembled, and the stack is already in place for meaningful source-level work.

.. seealso::

   `vyper-hol on GitHub <https://github.com/verifereum/vyper-hol>`_
      The open-source repository containing the formal semantics for Vyper and the EVM.

   `Verifereum project <https://verifereum.org>`_
      The project developing the HOL4 semantics and compiler verification work.

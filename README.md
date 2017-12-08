[![Join the chat at https://gitter.im/bethereum/viper](https://badges.gitter.im/ethereum/viper.svg)](https://gitter.im/ethereum/viper?utm_source=badge&utm_medium=badge&utm_campaign=pr-badge&utm_content=badge)
[![Build Status](https://travis-ci.org/ethereum/viper.svg?branch=master)](https://travis-ci.org/ethereum/viper)
[![Documentation Status](https://readthedocs.org/projects/viper/badge/?version=latest)](http://viper.readthedocs.io/en/latest/?badge=latest)
[![Coverage Status](https://coveralls.io/repos/github/ethereum/viper/badge.svg?branch=master)](https://coveralls.io/github/ethereum/viper?branch=master)

# Principles and Goals

Viper is an experimental programming language that aims for some of the following goals:

* **Security** - it should be possible and natural to build secure smart contracts in Viper.
* **Language and compiler simplicity** - the language and the compiler implementation should strive to be simple.
* **Auditability** - Viper code should be maximally human-readable. Furthermore, **it should be maximally difficult to write misleading code**. Simplicity for the reader is more important than simplicity for the writer, and simplicity for readers with low prior experience with Viper (and low prior experience with programming in general) is particularly important.

Some examples of what Viper does NOT have and why:

* **Modifiers** - eg. in Solidity you can do `function foo() mod1 { ... }`, where `mod1` can be defined elsewhere in the code to include a check that is done before execution, a check that is done after execution, some state changes, or possibly other things. Viper does not have this, because it makes it too easy to write misleading code. `mod1` just _looks_ too innocuous for something that could add arbitrary pre-conditions, post-conditions or state changes. Also, it encourages people to write code where the execution jumps around the file, harming auditability. The usual use case for a modifier is something that performs a single check before execution of a program; our recommendation is to simply inline these checks as asserts.
* **Class inheritance** - requires people to jump between multiple files to understand what a program is doing, and requires people to understand the rules of precedence in case of conflicts (which class's function X is the one that's actually used?). Hence, it makes code too complicated to understand.
* **Inline assembly** - adding inline assembly would make it no longer possible to Ctrl+F for a variable name to find all instances where that variable is read or modified.
* **Operator overloading** - waaay too easy to write misleading code (what do you mean "+" means "send all my money to the developer"? I didn't catch the part of the code that says that!).
* **Recursive calling** - cannot set an upper bound on gas limits, opening the door for gas limit attacks.
* **Infinite-length loops** - cannot set an upper bound on gas limits, opening the door for gas limit attacks.
* **Binary fixed point** - decimal fixed point is better, because any decimal fixed point value written as a literal in code has an exact representation, whereas with binary fixed point approximations are often required (eg. 0.2 -> 0.001100110011..., which needs to be truncated), leading to unintuitive results, eg. in python `0.3 + 0.3 + 0.3 + 0.1 != 1`.

Some changes that may be considered after Metropolis when [STATICCALL](https://github.com/ethereum/EIPs/pull/214/files) becomes available include:

* Forbidding state changes after non-static calls unless the address being non-statically called is explicitly marked "trusted". This would reduce risk of re-entrancy attacks.
* Forbidding "inline" non-static calls, eg. `send(some_address, contract.do_something_and_return_a_weivalue())`, enforcing clear separation between "call to get a response" and "call to do something".

Viper does NOT strive to be a 100% replacement for everything that can be done in Solidity; it will deliberately forbid things or make things harder if it deems fit to do so for the goal of increasing security.

**Note: Viper is still alpha software, use with care**

# Installation 
See the [Viper documentation](https://viper.readthedocs.io/en/latest/installing-viper.html)
for build instructions.

# Compiling a contract
To compile a contract, use:
```bash
    viper yourFileName.v.py
```

**Note: Since .vy is not official a language supported by any syntax highlights or linter,
it is recommended to name your viper file into `.v.py` to have a python highlights.**

There is also an [online compiler](https://viper.tools/) available you can use to experiment with
the language and compile to ``bytecode`` and/or ``LLL``.

**Note: While the viper version of the online compiler is updated on a regular basis it might
be a bit behind the latest version found in the master branch of this repository.**

## Testing (using pytest)
```bash
    python setup.py test
```

For testing strategy, please see [Testing](no-link)

# Contributing
* See Issues tab, and feel free to submit your own issues 
* Add PRs if you discover a solution to an existing issue
* For further discussions and questions talk to us on [gitter](https://gitter.im/ethereum/viper)
* For more information, see [Contributing](http://viper.readthedocs.io/en/latest/contributing.html)

############
Contributing
############

Help is always appreciated!

To get started, you can try `installing Vyper <https://vyper.readthedocs.io/en/latest/installing-vyper.html>`_ in order to familiarize
yourself with the components of Vyper and the build process. Also, it may be
useful to become well-versed at writing smart-contracts in Vyper.

Types of Contributions
======================

In particular, we need help in the following areas:

* Improving the documentation
* Responding to questions from other users on `StackExchange
  <https://ethereum.stackexchange.com>`_ and the `Vyper Gitter
  <https://gitter.im/ethereum/vyper>`_
* Suggesting Improvements
* Fixing and responding to `Vyper's GitHub issues <https://github.com/ethereum/vyper/issues>`_



How to Suggest Improvements
===========================

To suggest an improvement, please create a Vyper Improvement Proposal (VIP for short)
using the `VIP Template <https://github.com/ethereum/vyper/tree/master/.github/VIP_TEMPLATE.md>`_.

How to Report Issues
====================

To report an issue, please use the
`GitHub issues tracker <https://github.com/ethereum/vyper/issues>`_. When
reporting issues, please mention the following details:

* Which version of Vyper you are using
* What was the source code (if applicable)
* Which platform are you running on
* Your operating system name and version
* Detailed steps to reproduce the issue
* What was the result of the issue
* What the expected behaviour is

Reducing the source code that caused the issue to a bare minimum is always
very helpful and sometimes even clarifies a misunderstanding.

Fix Bugs
========

Find or report bugs at our `issues page <https://github.com/ethereum/vyper/issues>`_. Anything tagged with "bug" is open to whoever wants to implement it.

Workflow for Pull Requests
==========================

In order to contribute, please fork off of the ``master`` branch and make your
changes there. Your commit messages should detail *why* you made your change
in addition to *what* you did (unless it is a tiny change).

If you need to pull in any changes from ``master`` after making your fork (for
example, to resolve potential merge conflicts), please avoid using ``git merge``
and instead, ``git rebase`` your branch.

**Implement Features**

If you are writing a new feature, please ensure you write appropriate
Boost test cases and place them under ``tests/``.

If you are making a larger change, please consult first with the Gitter channel.

Although we do CI testing, please make sure that the tests pass for supported Python version and ensure that it builds locally before submitting a pull request.

Thank you for your help! ​

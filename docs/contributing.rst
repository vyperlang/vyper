.. _contributing:

Contributing
############

Help is always appreciated!

To get started, you can try `installing Vyper <installing-vyper.html>`_ in order to familiarize
yourself with the components of Vyper and the build process. Also, it may be
useful to become well-versed at writing smart-contracts in Vyper.

Types of Contributions
======================

In particular, we need help in the following areas:

* Improving the documentation
* Responding to questions from other users on `StackExchange
  <https://ethereum.stackexchange.com>`_ and `Discussions <https://github.com/vyperlang/vyper/discussions>`_
* Add to the discussions on the `Vyper (Smart Contract Programming Language) Discord <https://discord.gg/6tw7PTM7C2>`_
* Suggesting Improvements
* Fixing and responding to `Vyper's GitHub issues <https://github.com/vyperlang/vyper/issues>`_

How to Suggest Improvements
===========================

To suggest an improvement, please create a Vyper Improvement Proposal (VIP for short)
using the `VIP Template <https://github.com/vyperlang/vyper/blob/master/.github/ISSUE_TEMPLATE/vip.md>`_.

How to Report Issues
====================

To report an issue, please use the
`GitHub issues tracker <https://github.com/vyperlang/vyper/issues>`_. When
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

Find or report bugs at our `issues page <https://github.com/vyperlang/vyper/issues>`_. Anything tagged with "bug" is open to whoever wants to implement it.

Style Guide
===========

Our :ref:`style guide<style-guide>` outlines best practices for the Vyper repository. Please ask us on the `Vyper (Smart Contract Programming Language) Discord <https://discord.gg/6tw7PTM7C2>`_ ``#compiler-dev`` channel if you have questions about anything that is not outlined in the style guide.

Workflow for Pull Requests
==========================

In order to contribute, please fork off of the ``master`` branch and make your
changes there. Your commit messages should detail *why* you made your change
in addition to *what* you did (unless it is a tiny change).

If you need to pull in any changes from ``master`` after making your fork (for
example, to resolve potential merge conflicts), please avoid using ``git merge``
and instead, ``git rebase`` your branch.

Implementing New Features
-------------------------

If you are writing a new feature, please ensure you write appropriate Pytest test cases and place them under ``tests/``.

If you are making a larger change, please consult first with the `Vyper (Smart Contract Programming Language) Discord <https://discord.gg/6tw7PTM7C2>`_ ``#compiler-dev`` channel.

Although we do CI testing, please make sure that the tests pass for supported Python version and ensure that it builds locally before submitting a pull request.

Thank you for your help!

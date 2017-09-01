############
Contributing
############

Help is always appreciated!

To get started, you can try :ref:`building-from-source` in order to familiarize
yourself with the components of Viper and the build process. Also, it may be
useful to become well-versed at writing smart-contracts in Viper.

In particular, we need help in the following areas:

* Improving the documentation
* Responding to questions from other users on `StackExchange
  <https://ethereum.stackexchange.com>`_ and the `Viper Gitter
  <https://gitter.im/ethereum/viper>`_
* Fixing and responding to `Viper's GitHub issues
  <https://github.com/ethereum/viper/issues>`_


How to Report Issues
====================

To report an issue, please use the
`GitHub issues tracker <https://github.com/ethereum/viper/issues>`_. When
reporting issues, please mention the following details:

* Which version of Viper you are using
* What was the source code (if applicable)
* Which platform are you running on
* How to reproduce the issue
* What was the result of the issue
* What the expected behaviour is

Reducing the source code that caused the issue to a bare minimum is always
very helpful and sometimes even clarifies a misunderstanding.

Workflow for Pull Requests
==========================

In order to contribute, please fork off of the ``master`` branch and make your
changes there. Your commit messages should detail *why* you made your change
in addition to *what* you did (unless it is a tiny change).

If you need to pull in any changes from ``master`` after making your fork (for
example, to resolve potential merge conflicts), please avoid using ``git merge``
and instead, ``git rebase`` your branch.

Additionally, if you are writing a new feature, please ensure you write appropriate
Boost test cases and place them under ``tests/``.

However, if you are making a larger change, please consult with the Gitter
channel, first.

Also, even though we do CI testing, please test your code and
ensure that it builds locally before submitting a pull request.

Thank you for your help!

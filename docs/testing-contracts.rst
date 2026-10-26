.. _testing-contracts:

Testing a Contract
##################

For testing Vyper contracts we recommend the use of `pytest <https://docs.pytest.org/en/latest/contents.html>`_ along with one of the following frameworks:

Titanoboa
=========

`Titanoboa <https://github.com/vyperlang/titanoboa>`_ is a Vyper interpreter maintained by the Vyper team. It provides:

- Fast execution for testing
- Pretty tracebacks for debugging
- Forking capabilities
- Deployment features

**Getting Started:**

- `Official Titanoboa Documentation <https://titanoboa.readthedocs.io/en/latest/>`_

.. note::

    For comprehensive examples and best practices, refer to the official Titanoboa documentation linked above.

Moccasin
========

`Moccasin <https://github.com/Cyfrin/moccasin>`_ is a fast, Pythonic smart contract testing and development framework built on top of Titanoboa. It provides:

- ZKsync built-in support
- Named contracts for cleaner address management
- Custom pytest markers for staging tests
- Encrypted wallet support (no private keys in ``.env`` files)
- GitHub and Python dependency installation

**Getting Started:**

- `Official Moccasin Documentation <https://cyfrin.github.io/moccasin/>`_

.. _testing-contracts:

Testing a Contract
##################

For testing Vyper contracts we recommend the use of `pytest <https://docs.pytest.org/en/latest/contents.html>`_ along with `Titanoboa <https://github.com/vyperlang/titanoboa>`_.

.. seealso::

    :ref:`Compiling a Contract <vyper-cli-command>` for compilation options, and :ref:`Built-in Functions <built_in_functions>` for a complete function reference.

Titanoboa
=========

Titanoboa is a Vyper interpreter maintained by the Vyper team. It provides:

- Fast execution for testing
- Pretty tracebacks for debugging
- Forking capabilities
- Deployment features

**Getting Started:**

- `Official Titanoboa Documentation <https://titanoboa.readthedocs.io/>`_
- `Testing Reference <https://titanoboa.readthedocs.io/en/latest/testing.html>`_
- `API Reference <https://titanoboa.readthedocs.io/en/latest/api.html>`_

.. note::

    For comprehensive examples and best practices, refer to the official Titanoboa documentation linked above.

Other Frameworks
================

**Brownie** (`GitHub <https://github.com/eth-brownie/brownie>`_) is a Python-based development framework that was previously popular for Vyper testing. However, it is no longer actively maintained. If you encounter Brownie in existing projects, refer to its `documentation <https://eth-brownie.readthedocs.io/>`_, but for new projects we recommend Titanoboa.

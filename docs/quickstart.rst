.. _quickstart:

Quickstart
==========

This guide gets you from zero to a compiled Vyper contract in 5 minutes.

Which Framework Should I Use?
-----------------------------

**Short answer:** Use `Moccasin <https://github.com/cyfrin/moccasin>`_ for new projects.

Moccasin is a Vyper-first development framework built on Titanoboa (Vyper's native testing tool). It provides:

- Project scaffolding
- Compilation
- Testing with pytest (see :ref:`testing-contracts`)
- Deployment scripts
- Network management

If you're coming from Solidity/Foundry, Moccasin is the closest equivalent for Vyper.

.. note::
   
   **What about Foundry, Hardhat, or Ape?**
   
   - **Foundry:** Primarily for Solidity. Vyper support exists but requires workarounds.
   - **Hardhat:** JavaScript-based, has a Vyper plugin, but not the recommended path.
   - **Ape:** Good if you need multi-language support, but adds complexity.
   - **Brownie:** Deprecated. Do not use for new projects.

Prerequisites
-------------

- Python 3.11 or higher
- `uv <https://docs.astral.sh/uv/>`_ (recommended) or pip

.. note::

   If you're new to Python or having environment issues, see :ref:`troubleshooting-python` at the bottom of this page.

Installing Moccasin
-------------------

We recommend installing Moccasin using `uv <https://docs.astral.sh/uv/>`_:

.. code-block:: bash

   # Install uv (if you don't have it)
   curl -LsSf https://astral.sh/uv/install.sh | sh
   
   # Install Moccasin
   uv tool install moccasin

Verify it works:

.. code-block:: bash

   mox --version

You should see something like ``Moccasin CLI v0.4.3``.

.. note::

   **Using uv vs pip**
   
   We recommend ``uv tool install`` because it handles Python environment 
   isolation automatically. If you prefer pip, you can use ``pip install moccasin``, 
   but you may need to manage virtual environments yourself.

Creating a Project
------------------

.. code-block:: bash

   mox init my_project
   cd my_project

This creates a ready-to-use project structure:

.. code-block:: text

   my_project/
   ├── src/              # Your Vyper contracts
   ├── tests/            # Your tests  
   ├── script/           # Deployment scripts
   └── moccasin.toml     # Configuration

Moccasin generates a sample contract and test to get you started.

Compiling
---------

.. code-block:: bash

   mox compile

This compiles all ``.vy`` files in the ``src/`` folder.

Running Tests
-------------

.. code-block:: bash

   mox test

You should see output like:

.. code-block:: text

   ============================= test session starts ==============================
   collected 1 item                                                               
   tests/test_counter.py .                                                  [100%]
   ============================== 1 passed in 0.03s ===============================

Exploring the Sample Contract
-----------------------------

Open ``src/Counter.vy`` to see a minimal Vyper contract:

.. code-block:: vyper

   #pragma version ^0.4.1

   number: public(uint256)

   @external
   def set_number(new_number: uint256):
       self.number = new_number

   @external
   def increment():
       self.number += 1

This demonstrates:

- **Version pragma:** ``#pragma version ^0.4.1`` specifies the compiler version
- **State variables:** ``number: public(uint256)`` creates storage with an automatic getter
- **Functions:** ``@external`` marks functions callable from outside the contract

Next Steps
----------

- Browse :doc:`vyper-by-example/index` for more complex contracts
- Read about :doc:`types` and :doc:`control-structures`
- Learn about :doc:`using-modules` for code reuse
- See the `Moccasin documentation <https://cyfrin.github.io/moccasin/>`_ for deployment and advanced features

.. _troubleshooting-python:

Troubleshooting
---------------

**"command not found: mox"**

If you installed with ``uv tool install``, restart your terminal or run:

.. code-block:: bash

   source ~/.bashrc  # or ~/.zshrc on macOS

**"pip install moccasin" fails**

Use uv instead:

.. code-block:: bash

   curl -LsSf https://astral.sh/uv/install.sh | sh
   uv tool install moccasin

**Python version issues**

Moccasin requires Python 3.11+. Check your version:

.. code-block:: bash

   python3 --version
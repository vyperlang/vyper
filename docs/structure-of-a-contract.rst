.. _contract_structure:

Structure of a Contract
#######################

Vyper contracts are contained within files. Each file contains exactly one contract.

This section provides a quick overview of the types of data present within a contract, with links to other sections where you can obtain more details.

.. _structure-versions:

Pragmas
=======

Vyper supports several source code directives to control compiler modes and help with build reproducibility.

Version Pragma
--------------

The version pragma ensures that a contract is only compiled by the intended compiler version, or range of versions. Version strings use `NPM <https://docs.npmjs.com/about-semantic-versioning>`_ style syntax. Starting from v0.4.0 and up, version strings will use `PEP440 version specifiers <https://peps.python.org/pep-0440/#version-specifiers>`_.

As of 0.3.10, the recommended way to specify the version pragma is as follows:

.. code-block:: vyper

    #pragma version ^0.3.0

.. note::

    Both pragma directive versions ``#pragma`` and ``# pragma`` are supported.

The following declaration is equivalent, and, prior to 0.3.10, was the only supported method to specify the compiler version:

.. code-block:: vyper

    # @version ^0.3.0


In the above examples, the contract will only compile with Vyper versions ``0.3.x``.

Optimization Mode
-----------------

The optimization mode can be one of ``"none"``, ``"codesize"``, or ``"gas"`` (default). For example, adding the following line to a contract will cause it to try to optimize for codesize:

.. code-block:: vyper

   #pragma optimize codesize

The optimization mode can also be set as a compiler option, which is documented in :ref:`optimization-mode`. If the compiler option conflicts with the source code pragma, an exception will be raised and compilation will not continue.

EVM Version
-----------------

The EVM version can be set with the ``evm-version`` pragma, which is documented in :ref:`evm-version`.

Experimental Code Generation
-----------------
The new experimental code generation feature can be activated using the following directive:

.. code-block:: vyper

   #pragma experimental-codegen

Alternatively, you can use the alias ``"venom"`` instead of ``"experimental-codegen"``  to enable this feature.

Imports
=======

Import statements allow you to import :ref:`modules` or :ref:`interfaces` with the ``import`` or ``from ... import`` syntax.

Imports via ``import``
----------------------

You may import modules (defined in ``.vy`` files) and interfaces (defined in ``.vyi`` or ``.json`` files) via ``import`` statements. You may use plain or ``as`` variants.

.. code-block:: vyper

    # without an alias
    import foo

    # with an alias
    import my_package.foo as bar

Imports via ``from ... import``
-------------------------------

Using ``from`` you can perform both absolute and relative imports. You may optionally include an alias - if you do not, the name of the interface will be the same as the file.

.. code-block:: vyper

    # without an alias
    from my_package import foo

    # with an alias
    from my_package import foo as bar

Relative imports are possible by prepending dots to the contract name. A single leading dot indicates a relative import starting with the current package. Two leading dots indicate a relative import from the parent of the current package:

.. code-block:: vyper

    from . import foo
    from ..interfaces import baz

Further higher directories can be accessed with ``...``, ``....`` etc., as in Python.

.. _searching_for_imports:

Searching For Imports
-----------------------------

When looking for a file to import, Vyper will first search relative to the same folder as the contract being compiled. It then checks for the file in the provided search paths, in the precedence provided. Vyper checks for the file name with a ``.vy`` suffix first, then ``.vyi``, then ``.json``.

When using the :ref:`vyper CLI <vyper-cli-command>`, the search path defaults to the current working directory, plus the python `syspath <https://docs.python.org/3.11/library/sys.html#sys.path>`_. You can append to the search path with the ``-p`` flag, e.g.:

::

    $ vyper my_project/contracts/my_contract.vy -p ../path/to/other_project

In the above example, the ``my_project`` folder is set as the root path.

.. note::

    Including the python syspath on the search path means that any Vyper module in the current ``virtualenv`` is discoverable by the Vyper compiler, and Vyper packages can be published to and installed from PyPI and accessed via ``import`` statements with no additional configuration. Keep in mind that best practice is always to install packages *within* a ``virtualenv`` and not globally!

You can additionally disable the behavior of adding the syspath to the search path with the CLI flag ``--disable-sys-path``:

::

    $ vyper --disable-sys-path my_project/my_contract.vy

When compiling from a :ref:`.vyz archive file <vyper-archives>` or :ref:`standard json input <vyper-json>`, the search path is already part of the bundle, it cannot be changed from the command line.

.. _structure-state-variables:

State Variables
===============

State variables are values which are permanently stored in contract storage. They are declared outside of the body of any functions, and initially contain the :ref:`default value<types-initial>` for their type.

.. code-block:: vyper

    storedData: int128

State variables are accessed via the :ref:`self<constants-self>` object.

.. code-block:: vyper

    self.storedData = 123

See the documentation on :ref:`Types<types>` or :ref:`Scoping and Declarations<scoping>` for more information.

.. _structure-functions:

Functions
=========

Functions are executable units of code within a contract.

.. code-block:: vyper

    @external
    def bid():
        ...

Functions may be called internally or externally depending on their :ref:`visibility <function-visibility>`. Functions may accept input arguments and return variables in order to pass values between them.

See the :ref:`Functions <control-structures-functions>` documentation for more information.

.. _modules:

Modules
==========

A module is a set of function definitions and variable declarations which enables code reuse. Vyper favors code reuse through composition, rather than inheritance.

Broadly speaking, a module contains:

* function definitions
* state variable declarations
* type definitions

Therefore, a module encapsulates

* functionality (types and functions), and
* state (variables), which may be tightly coupled with that functionality 

Modules can be added to contracts by importing them from a ``.vy`` file. Any ``.vy`` file is a valid module which can be imported into another contract! This is a very powerful feature which allows you to assemble contracts via other contracts as building blocks.

.. code-block:: vyper
    # my_module.vy

    def perform_some_computation() -> uint256:
        return 5

    @external
    def some_external_function() -> uint256:
        return 6

.. code-block:: vyper
    import my_module

    exports: my_module.some_external_function

    @external
    def foo() -> uint256:
        return my_module.perform_some_computation()

Modules are opt-in by design. That is, any operations involving state or exposing external functions must be explicitly opted into using the ``exports``, ``uses`` or ``initializes`` keywords. See the :ref:`Modules <modules>` documentation for more information.

Events
======

Events provide an interface for the EVM's logging facilities. Events may be logged with specially indexed data structures that allow clients, including light clients, to efficiently search for them.

.. code-block:: vyper

    event Payment:
        amount: int128
        sender: indexed(address)

    total_paid: int128

    @external
    @payable
    def pay():
        self.total_paid += msg.value
        log Payment(msg.value, msg.sender)

See the :ref:`Event <event-logging>` documentation for more information.

.. _interfaces:

Interfaces
==========

An interface is a set of function definitions used to enable calls between smart contracts. A contract interface defines all of that contract's externally available functions. By importing the interface, your contract now knows how to call these functions in other contracts.

Interfaces can be added to contracts either through inline definition, or by importing them from a separate ``.vyi`` file.

.. code-block:: vyper

    interface FooBar:
        def calculate() -> uint256: view
        def test1(): nonpayable

.. code-block:: vyper

    from foo import FooBar

Once defined, an interface can then be used to make external calls to a given address:

.. code-block:: vyper

    @external
    def test(some_address: address):
        FooBar(some_address).calculate()

See the :ref:`Interfaces <interfaces>` documentation for more information.

Structs
=======

A struct is a custom defined type that allows you to group several variables together:

.. code-block:: vyper

    struct MyStruct:
        value1: int128
        value2: decimal

See the :ref:`Structs <types-struct>` documentation for more information.

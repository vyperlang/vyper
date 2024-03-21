Compiling a Contract
********************

Command-Line Compiler Tools
===========================

Vyper includes the following command-line scripts for compiling contracts:

* ``vyper``: Compiles vyper contract files into ``IR`` or bytecode
* ``vyper-json``: Provides a JSON interface to the compiler

.. note::

    The ``--help`` flag gives verbose explanations of how to use each of these scripts.

vyper
-----

``vyper`` provides command-line access to the compiler. It can generate various outputs including simple binaries, ASTs, interfaces and source mappings.

To compile a contract:

.. code:: shell

    $ vyper yourFileName.vy


Include the ``-f`` flag to specify which output formats to return. Use ``vyper --help`` for a full list of output options.

.. code:: shell

    $ vyper -f abi,abi_python,bytecode,bytecode_runtime,interface,external_interface,ast,annotated_ast,ir,ir_json,ir_runtime,hex-ir,asm,opcodes,opcodes_runtime,source_map,method_identifiers,userdoc,devdoc,metadata,combined_json,layout yourFileName.vy

.. note::
    The ``opcodes`` and ``opcodes_runtime`` output of the compiler has been returning incorrect opcodes since ``0.2.0`` due to a lack of 0 padding (patched via `PR 3735 <https://github.com/vyperlang/vyper/pull/3735>`_). If you rely on these functions for debugging, please use the latest patched versions.

The ``-p`` flag allows you to set a root path that is used when searching for interface files to import.  If none is given, it will default to the current working directory. See :ref:`searching_for_imports` for more information.

.. code:: shell

    $ vyper -p yourProject yourProject/yourFileName.vy


.. _compiler-storage-layout:

Storage Layout
~~~~~~~~~~~~~~

To display the default storage layout for a contract:

.. code:: shell

    $ vyper -f layout yourFileName.vy

This outputs a JSON object detailing the locations for all state variables as determined by the compiler.

To override the default storage layout for a contract:

.. code:: shell

    $ vyper --storage-layout-file storageLayout.json yourFileName.vy

The input to the ``--storage-layout-file`` flag must match the format of the ``.storage_layout`` field from the ``vyper -f layout`` command.


.. _vyper-json:

vyper-json
----------

``vyper-json`` provides a JSON interface for the compiler. It expects a :ref:`JSON formatted input<vyper-json-input>` and returns the compilation result in a :ref:`JSON formatted output<vyper-json-output>`.

To compile from JSON supplied via ``stdin``:

.. code:: shell

    $ vyper-json

To compile from a JSON file:

.. code:: shell

    $ vyper-json yourProject.json

By default, the output is sent to ``stdout``. To redirect to a file, use the ``-o`` flag:

.. code:: shell

    $ vyper-json -o compiled.json

Importing Interfaces
~~~~~~~~~~~~~~~~~~~~

``vyper-json`` searches for imported interfaces in the following sequence:

1. Interfaces defined in the ``interfaces`` field of the input JSON.
2. Derived interfaces generated from contracts in the ``sources`` field of the input JSON.
3. (Optional) The local filesystem, if a root path was explicitly declared via the ``-p`` flag.

See :ref:`searching_for_imports` for more information on Vyper's import system.

Online Compilers
================

Try VyperLang!
-----------------

`Try VyperLang! <https://try.vyperlang.org>`_ is a JupterHub instance hosted by the Vyper team as a sandbox for developing and testing contracts in Vyper. It requires github for login, and supports deployment via the browser.

Remix IDE
---------

`Remix IDE <https://remix.ethereum.org>`_ is a compiler and JavaScript VM for developing and testing contracts in Vyper, as well as Solidity.

.. note::

   While the Vyper version of the Remix IDE compiler is updated on a regular basis, it might be a bit behind the latest version found in the master branch of the repository. Make sure the byte code matches the output from your local compiler.

.. _optimization-mode:

Compiler Optimization Modes
===========================

The vyper CLI tool accepts an optimization mode ``"none"``, ``"codesize"``, or ``"gas"`` (default). It can be set using the ``--optimize`` flag. For example, invoking ``vyper --optimize codesize MyContract.vy`` will compile the contract, optimizing for code size. As a rough summary of the differences between gas and codesize mode, in gas optimized mode, the compiler will try to generate bytecode which minimizes gas (up to a point), including:

* using a sparse selector table which optimizes for gas over codesize
* inlining some constants, and
* trying to unroll some loops, especially for data copies.

In codesize optimized mode, the compiler will try hard to minimize codesize by

* using a dense selector table
* out-lining code, and
* using more loops for data copies.


.. _evm-version:

Setting the Target EVM Version
==============================

When you compile your contract code, you can specify the target Ethereum Virtual Machine version to compile for, to access or avoid particular features. You can specify the version either with a source code pragma or as a compiler option. It is recommended to use the compiler option when you want flexibility (for instance, ease of deploying across different chains), and the source code pragma when you want bytecode reproducibility (for instance, when verifying code on a block explorer).

.. note::
   If the evm version specified by the compiler options conflicts with the source code pragma, an exception will be raised and compilation will not continue.

For instance, the adding the following pragma to a contract indicates that it should be compiled for the "shanghai" fork of the EVM.

.. code-block:: vyper

   #pragma evm-version shanghai

.. warning::

    Compiling for the wrong EVM version can result in wrong, strange, or failing behavior. Please ensure, especially if running a private chain, that you use matching EVM versions.

When compiling via the ``vyper`` CLI, you can specify the EVM version option using the ``--evm-version`` flag:

.. code:: shell

    $ vyper --evm-version [VERSION]

When using the JSON interface, you can include the ``"evmVersion"`` key within the ``"settings"`` field:

.. code-block:: json

    {
        "settings": {
            "evmVersion": "[VERSION]"
        }
    }

Target Options
--------------

The following is a list of supported EVM versions, and changes in the compiler introduced with each version. Backward compatibility is not guaranteed between each version. In general, the compiler team maintains an informal policy that the compiler will support 3 years of hard fork rulesets, but this policy may be revisited as appropriate.


.. py:attribute:: london

.. py:attribute:: paris

   - ``block.difficulty`` is deprecated in favor of its new alias, ``block.prevrandao``.

.. py:attribute:: shanghai (default)

   - The ``PUSH0`` opcode is automatically generated by the compiler instead of ``PUSH1 0``

.. py:attribute:: cancun (experimental)

   - The ``transient`` keyword allows declaration of variables which live in transient storage
   - Functions marked with ``@nonreentrant`` are protected with TLOAD/TSTORE instead of SLOAD/SSTORE
   - The ``MCOPY`` opcode will be generated automatically by the compiler for most memory operations.


Compiler Input and Output JSON Description
==========================================

Especially when dealing with complex or automated setups, the recommended way to compile is to use :ref:`vyper-json` and the JSON-input-output interface.

Where possible, the Vyper JSON compiler formats follow those of `Solidity <https://solidity.readthedocs.io/en/latest/using-the-compiler.html#compiler-input-and-output-json-description>`_.

.. _vyper-json-input:

Input JSON Description
----------------------

The following example describes the expected input format of ``vyper-json``. Comments are of course not permitted and used here *only for explanatory purposes*.

.. code-block:: json

    {
        // Required: Source code language. Must be set to "Vyper".
        "language": "Vyper",
        // Required
        // Source codes given here will be compiled.
        "sources": {
            "contracts/foo.vy": {
                // Optional: keccak256 hash of the source file
                "keccak256": "0x234...",
                // Required: literal contents of the source file
                "content": "@external\ndef foo() -> bool:\n    return True"
            }
        },
        // Optional
        // Interfaces given here are made available for import by the sources
        // that are compiled. If the suffix is ".vy", the compiler will expect
        // a contract-as-interface using proper Vyper syntax. If the suffix is
        // "abi" the compiler will expect an ABI object.
        "interfaces": {
            "contracts/bar.vy": {
                "content": ""
            },
            "contracts/baz.json": {
                "abi": []
            }
        },
        // Optional
        "settings": {
            "evmVersion": "shanghai",  // EVM version to compile for. Can be london, paris, shanghai (default) or cancun (experimental!).
            // optional, optimization mode
            // defaults to "gas". can be one of "gas", "codesize", "none",
            // false  and true (the last two are for backwards compatibility).
            "optimize": "gas",
            // optional, whether or not the bytecode should include Vyper's signature
            // defaults to true
            "bytecodeMetadata": true,
            // The following is used to select desired outputs based on file names.
            // File names are given as keys, a star as a file name matches all files.
            // Outputs can also follow the Solidity format where second level keys
            // denoting contract names - all 2nd level outputs are applied to the file.
            //
            // To select all possible compiler outputs: "outputSelection: { '*': ["*"] }"
            // Note that this might slow down the compilation process needlessly.
            //
            // The available output types are as follows:
            //
            //    abi - The contract ABI
            //    ast - Abstract syntax tree
            //    interface - Derived interface of the contract, in proper Vyper syntax
            //    ir - intermediate representation of the code
            //    userdoc - Natspec user documentation
            //    devdoc - Natspec developer documentation
            //    evm.bytecode.object - Bytecode object
            //    evm.bytecode.opcodes - Opcodes list
            //    evm.deployedBytecode.object - Deployed bytecode object
            //    evm.deployedBytecode.opcodes - Deployed opcodes list
            //    evm.deployedBytecode.sourceMap - Solidity-style source mapping
            //    evm.deployedBytecode.sourceMapFull - Deployed source mapping (useful for debugging)
            //    evm.methodIdentifiers - The list of function hashes
            //
            // Using `evm`, `evm.bytecode`, etc. will select every target part of that output.
            // Additionally, `*` can be used as a wildcard to request everything.
            // Note that the sourceMapFull.pc_ast_map is the recommended source map to use;
            // the other types are included for legacy and compatibility reasons.
            //
            "outputSelection": {
                "*": ["evm.bytecode", "abi"],  // Enable the abi and bytecode outputs for every single contract
                "contracts/foo.vy": ["ast"]  // Enable the ast output for contracts/foo.vy
            }
        }
    }

.. _vyper-json-output:

Output JSON Description
-----------------------

The following example describes the output format of ``vyper-json``. Comments are of course not permitted and used here *only for explanatory purposes*.

.. code-block:: json

    {
        // The compiler version used to generate the JSON
        "compiler": "vyper-0.1.0b12",
        // Optional: not present if no errors/warnings were encountered
        "errors": [
            {
            // Optional: Location within the source file.
            "sourceLocation": {
                "file": "source_file.vy",
                "lineno": 5,
                "col_offset": 11
            },
            // Mandatory: Exception type, such as "JSONError", "StructureException", etc.
            "type": "TypeMismatch",
            // Mandatory: Component where the error originated, such as "json", "compiler", "vyper", etc.
            "component": "compiler",
            // Mandatory ("error" or "warning")
            "severity": "error",
            // Mandatory
            "message": "Unsupported type conversion: int128 to bool"
            // Optional: the message formatted with source location
            "formattedMessage": "line 5:11 Unsupported type conversion: int128 to bool"
            }
        ],
        // This contains the file-level outputs. Can be limited/filtered by the outputSelection settings.
        "sources": {
            "source_file.vy": {
                // Identifier of the source (used in source maps)
                "id": 0,
                // The AST object
                "ast": {},
            }
        },
        // This contains the contract-level outputs. Can be limited/filtered by the outputSelection settings.
        "contracts": {
            "source_file.vy": {
                // The contract name will always be the file name without a suffix
                "source_file": {
                    // The Ethereum Contract ABI.
                    // See https://github.com/ethereum/wiki/wiki/Ethereum-Contract-ABI
                    "abi": [],
                    // Natspec developer documentation
                    "devdoc": {},
                    // Intermediate representation (string)
                    "ir": "",
                    // Natspec developer documentation
                    "userdoc": {},
                    // EVM-related outputs
                    "evm": {
                        "bytecode": {
                            // The bytecode as a hex string.
                            "object": "00fe",
                            // Opcodes list (string)
                            "opcodes": ""
                        },
                        "deployedBytecode": {
                            // The deployed bytecode as a hex string.
                            "object": "00fe",
                            // Deployed opcodes list (string)
                            "opcodes": "",
                            // The deployed source mapping as a string.
                            "sourceMap": ""
                        },
                        // The list of function hashes
                        "methodIdentifiers": {
                            "delegate(address)": "5c19a95c"
                        }
                    }
                }
            }
        }
    }

Errors
~~~~~~

Each error includes a ``component`` field, indicating the stage at which it occurred:

* ``json``: Errors that occur while parsing the input JSON. Usually, a result of invalid JSON or a required value that is missing.
* ``parser``: Errors that occur while parsing the contracts. Usually, a result of invalid Vyper syntax.
* ``compiler``: Errors that occur while compiling the contracts.
* ``vyper``: Unexpected errors that occur within Vyper. If you receive an error of this type, please open an issue.

You can also use the ``--traceback`` flag to receive a standard Python traceback when an error is encountered.

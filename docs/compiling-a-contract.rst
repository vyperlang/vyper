Compiling a Contract
********************

Command-Line Tools
==================

Vyper includes the following command-line scripts for compiling contracts:

* ``vyper``: Compiles vyper contract files into ``LLL`` or bytecode
* ``vyper-json``: Provides a JSON interface to the compiler

.. note::

    The ``--help`` flag gives verbose explanations of how to use each of these scripts.

vyper
-----

``vyper`` provides command-line access to the compiler. It can generate various outputs including simple binaries, ASTs, interfaces and source mappings.

To compile a contract:

::

    $ vyper yourFileName.vy


Include the ``-f`` flag to specify which output formats to return. Use ``vyper --help`` for a full list of output options.

::

    $ vyper -f abi,bytecode,bytecode_runtime,ir,asm,source_map,method_identifiers yourFileName.vy

The ``-p`` flag allows you to set a root path that is used when searching for interface files to import.  If none is given, it will default to the current working directory. See :ref:`searching_for_imports` for more information.

::

    $ vyper -p yourProject yourProject/yourFileName.vy


vyper-json
----------

``vyper-json`` provides a JSON interface for the compiler. It expects a JSON formatted input and returns the compilation result in a JSON formatted output.

Where possible, the JSON formats used by this script follow those of `Solidity <https://solidity.readthedocs.io/en/latest/using-the-compiler.html#compiler-input-and-output-json-description>`_.

To compile from JSON supplied via ``stdin``:

::

    $ vyper-json

To compile from a JSON file:

::

    $ vyper-json yourProject.json

By default, the output is sent to ``stdout``. To redirect to a file, use the ``-o`` flag:

::

    $ vyper-json -o compiled.json

Input JSON Description
~~~~~~~~~~~~~~~~~~~~~~

The following example describes the expected input format of ``vyper-json``. Comments are of course not permitted and used here only for explanatory purposes.

.. code-block:: javascript

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
                "content": "@public\ndef foo() -> bool:\n    return True"
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
            "evmVersion": "byzantium"  // EVM version to compile for. Can be byzantium, constantinople or petersburg.
        },
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
        //    ir - LLL intermediate representation of the code
        //    evm.bytecode.object - Bytecode object
        //    evm.bytecode.opcodes - Opcodes list
        //    evm.deployedBytecode.object - Deployed bytecode object
        //    evm.deployedBytecode.opcodes - Deployed opcodes list
        //    evm.deployedBytecode.sourceMap - Deployed source mapping (useful for debugging)
        //    evm.methodIdentifiers - The list of function hashes
        //
        // Using `evm`, `evm.bytecode`, etc. will select every target part of that output.
        // Additionally, `*` can be used as a wildcard to request everything.
        //
        "outputSelection": {
            "*": ["evm.bytecode", "abi"],  // Enable the abi and bytecode outputs for every single contract
            "contracts/foo.vy": ["ast"]  // Enable the ast output for contracts/foo.vy
        }
    }

Output JSON Description
~~~~~~~~~~~~~~~~~~~~~~~

The following example describes the output format of ``vyper-json``. Comments are of course not permitted and used here only for explanatory purposes.

.. code-block:: javascript

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
            // Mandatory: Exception type, such as "JSONError", "KeyError", "StructureException", etc.
            "type": "TypeMismatchException",
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
                    // Intermediate representation (string)
                    "ir": "",
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

Importing Interfaces
~~~~~~~~~~~~~~~~~~~~

``vyper-json`` searches for imported interfaces in the following sequence:

1. Interfaces defined in the ``interfaces`` field of the input JSON
2. Derived interfaces generated from contracts in the ``sources`` field of the input JSON
3. (Optional) The local filesystem, if a root path was explicitely declared via the ``-p`` flag.

See :ref:`searching_for_imports` for more information on Vyper's import system.

Errors
~~~~~~

Each error includes a ``component`` field, indicating the stage at which it occurred:

* ``json``: Errors that occur while parsing the input JSON. Usually a result of invalid JSON or a required value that is missing.
* ``parser``: Errors that occur while parsing the contracts. Usually a result of invalid Vyper syntax.
* ``compiler``: Errors that occur while compiling the contracts.
* ``vyper``: Unexpected errors that occur within Vyper. If you receive an error of this type, please open an issue.

You can also use the ``--traceback`` flag to receive a standard Python traceback when an error is encountered.


Online Compilers
================

Vyper Online Compiler
---------------------

`Vyper Online Compiler <https://vyper.online/>`_ is an online compiler which lets you experiment with the language without having to install Vyper. It allows you to compile to ``bytecode`` as well as ``LLL``.

.. note::

    While the vyper version of the online compiler is updated on a regular basis it might be a bit behind the latest version found in the master branch of the repository.

Remix IDE
---------

`Remix IDE <https://remix.ethereum.org>`_ is a compiler and Javascript VM for developing and testing contracts in Vyper as well as Solidity.

.. note::

   While the vyper version of the Remix IDE compiler is updated on a regular basis it might be a bit behind the latest version found in the master branch of the repository. Make sure the byte code matches the output from your local compiler.

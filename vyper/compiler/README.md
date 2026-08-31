# 🐍 `vyper.compiler` 🐍

## Purpose

The `vyper.compiler` module contains the main user-facing functionality used to compile
vyper source code and generate various compiler outputs.

## Organization

`vyper.compiler` has the following structure:

* [`__init__.py`](__init__.py): Contains the `compile_codes` function, which is the
primary function used for compiling Vyper source code.
* [`phases.py`](phases.py): Pure functions for executing each compiler phase, as well
as the `CompilerData` object that fetches and stores compiler output for each phase.
* [`output.py`](output.py): Functions that convert compiler data into the final
formats to be outputted to the user.
* [`utils.py`](utils.py): Various utility functions related to compilation.

## Control Flow

### Compiler Phases

The compilation process includes the following broad phases:

1. In [`vyper.ast`](../ast), the source code is parsed and converted to an
abstract syntax tree.
1. In [`vyper.codegen.module`](../codegen/module.py), the contextualized nodes are
converted into IR nodes.
1. In [`vyper.compile_ir`](../ir/compile_ir.py), the IR nodes are converted to
assembly instructions.
1. In [`vyper.compile_ir`](../ir/compile_ir.py), the assembly is converted to EVM
bytecode.

Additionally, phases 3-5 may produce two output types:

* **Deployment** bytecode, used for deploying the contract onto the blockchain
* **Runtime** bytecode, the on-chain code created as a result of deployment

[`phases.py`](phases.py) contains high-level pure functions for executing each
compiler phase. These functions typically accept the result of one or more
previous phases as input and return the newly generated data. See their docstrings
for specific implementation details.

### Generating Compiler Outputs

[`vyper.compiler.compile_codes`](__init__.py) is the main user-facing function for
generating compiler output from Vyper source. The process is as follows:

1. A [`CompilerData`](phases.py) object is created for each contract to be compiled.
This object uses `@property` methods to trigger phases of the compiler as required.
2. Functions in [`output.py`](output.py) generate the requested outputs from the
compiler data.

## Design

### Naming Conventions

We use the following naming conventions throughout this module, to aid readability:

* `source_code` refers to the original source code as string
* `vyper_module` refers to the top-level `Module` Vyper AST node, created from the
source code
* `global_ctx` refers to the `ModuleT` object
* `ir_nodes` refers to the top-level `IRnode`, created from the AST
* `assembly` refers to a `list` of assembly instructions generated from the IR
* `bytecode` refers to the final, generated `bytecode` as a `bytes` string.
* `compiler_data` refers to the `CompilerData` object

### `CompilerData` and Compiler Output Types

The `CompilerData` object provides access to the output data of each compiler phase.
Compiler phases are executed on-demand and the resulting data stored within the
object. This way we ensure that only the data which is required is generated,
and that each data set is only generated once.

Compiler output format are listed in the `OUTPUT_FORMATS` variable within
[`__init__.py`](__init__.py). Each format is mapped to a generation function in
[`output.py`](output.py). These functions each receive the `CompilerData` object
as a single function.

## Integration

Compiler data should always be accessed via one of the compiler functions made
available in the root `vyper` module:

```python
from vyper import compile_code, compile_codes
```

See the docstrings for these functions to learn how they are used.

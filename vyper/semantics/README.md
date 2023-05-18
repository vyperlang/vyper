# 🐍 `vyper.semantics` 🐍

## Purpose

The `vyper.semantics` package performs syntax verification, type checking and semantics analysis of a
Vyper abstract syntax tree (AST).

## Organization

`vyper.semantics` has the following structure:

* [`types/`](types): Subpackage of classes and methods used to represent types
  * [`bases.py`](types/bases.py): Common base classes for all type objects
  * [`bytestrings.py`](types/bytestrings.py): Single-value subscript types (bytes, string)
  * [`function.py`](types/function.py): Contract function and member function types
  * [`primitives.py`](types/primitives.py): Address, boolean, fixed length byte, integer and decimal types
  * [`shortcuts.py`](types/shortcuts.py): Helper constants for commonly used types
  * [`subscriptable.py`](types/subscriptable.py): Mapping, array and tuple types
  * [`user.py`](types/user.py): Enum, event, interface and struct types
  * [`utils.py`](types/utils.py): Functions for generating and fetching type objects
* [`analysis/`](analysis): Subpackage for type checking and syntax verification logic
  * [`annotation.py`](analysis/annotation.py): Annotates statements and expressions with the appropriate type information
  * [`base.py`](analysis/base.py): Base validation class
  * [`common.py`](analysis/common.py): Base AST visitor class
  * [`data_positions`](analysis/data_positions.py): Functions for tracking storage variables and allocating storage slots
  * [`levenhtein_utils.py`](analysis/levenshtein_utils.py): Helper for better error messages
  * [`local.py`](analysis/local.py): Validates the local namespace of each function within a contract
  * [`module.py`](analysis/module.py): Validates the module namespace of a contract.
  * [`utils.py`](analysis/utils.py): Functions for comparing and validating types
* [`data_locations.py`](data_locations.py): `DataLocation` object for type location information
* [`environment.py`](environment.py): Environment variables and builtin constants
* [`namespace.py`](namespace.py): `Namespace` object, a `dict` subclass representing the namespace of a contract

## Control Flow

The [`analysis`](analysis) subpackage contains the top-level `validate_semantics`
function. This function is used to verify and type-check a contract. The process
consists of three steps:

1. Preparing the builtin namespace
2. Validating the module-level scope
3. Annotating and validating local scopes

### 1. Preparing the builtin namespace

The [`Namespace`](namespace.py) object represents the namespace for a contract.
Builtins are added upon initialization of the object. This includes:

* Adding type classes from the [`types/`](types) subpackage
* Adding environment variables and builtin constants from [`environment.py`](environment.py)
* Adding builtin functions from the [`functions`](../builtins/functions.py) package
* Adding / resetting `self` and `log`

### 2. Validating the Module Scope

[`validation/module.py`](validation/module.py) validates the module-level scope
of a contract. This includes:

* Generating user-defined types (e.g. structs and interfaces)
* Creating type definitions for storage variables, user-defined constants, events
and functions
* Validating import statements and function signatures

### 3. Annotating and validating the Local Scopes

[`validation/local.py`](validation/local.py) validates the local scope within each
function in a contract. `FunctionNodeVisitor` is used to iterate over the statement
nodes in each function body, annotate them and apply appropriate checks.

To learn more about the checks on each node type, read the docstrings on the methods
of `FunctionNodeVisitor`.

## Design

### Type Checking

Type checking is handled bottom-up.

1. The type of each expression is evaluated independently.
2. Multiple types within the left-hand or right-hand side are compared (e.g. a
literal array).
3. The left-hand and right-hand types are compared.
4. The operation being performed is validated according to the types (e.g. in a
math operation, the types must be numeric)

In type-checking the following example:

```python
foo: int128[2] = [-2, 42]
```

1. The annotation value is validated and determined to be an `int128` array of
length `2`.
2. The literal array values are validated on their own. The first value must be
`int128`, the second could be `int128` or `uint256`.
3. The right-hand side types are compared. A common type of `int128` is found.
The array is given a type of `int128[2]`.
4. The left-hand and right-hand types are compared and found to be matching.
5. A new type definition `int128[2]` is added to the namespace with the name `foo`.

### Types Classes

All type classes are found within the [`semantics/types/`](types) subpackage.

### Namespace

[`namespace.py`](namespace.py) contains the `Namespace` object. `Namespace` is a
`dict` subclass representing the namespace of a contract. It imposes several
additional restrictions:

* Attempting to replace an existing field raises `NamespaceCollision`
* Attempting to access a key that does not exist raises `UndeclaredDefinition`

To ensure that only one copy of `Namespace` exists throughout the package, you
should access it using the `get_namespace` method:

```python
from vyper.semantics.namespace import get_namespace

namespace = get_namespace()
```

#### Scoping and Namespace as a Context Manager

Each smart contract in Vyper uses a unique namespace, and has three primary scopes:

* **builtin**: core types, environment variables and builtin functions
* **module**: contract functions, storage variables and user-defined constants
* **local**: memory variables and other objects declared within a single contract
function

Additionally, a new scope is entered for each execution of a `for` loop or branch
of an `if` statement.

Scoping is handled by calling `Namespace.enter_scope` as a
[context manager](https://docs.python.org/3/reference/datamodel.html#with-statement-context-managers).
Values added while inside the context are removed when the context is exited.

```python
with namespace.enter_scope():
    namespace['foo'] = 42

namespace['foo']  # this raises an UndeclaredDefinition
```

### Validation

Validation is handled by calling methods within each type object. In general:

* Type objects include one or both of `from_annotation` and `from_literal`
methods, which validate an AST node and produce a type object
* Type objects include a variety of `get_<thing>` and `validate_<action>` methods,
which are used to validate interactions and obtain new types based on AST nodes

All possible methods for type objects are outlined within the base
classes in [`types/bases.py`](types/bases.py). The functionality within the methods
of the base classes is typically to raise and give a meaningful explanation
for _why_ the syntax not valid.

Here are some examples:

#### 1. Declaring a Variable

```python
foo: int128
```

1. We look up `int128` in `namespace`. We retrieve an `IntegerT` object.
3. We store the new definition under the key `foo` within `namespace`.

#### 2. Modifying the value of a variable

```python
foo += 6
```

1. We look up `foo` in `namespace` and retrieve an `IntegerT` with `_is_signed=True` and `_bits=128`.
2. We call `get_potential_types_from_node` with the target node
and are returned a list of types that are valid for the literal `6`. In this
case, the list includes an `IntegerT` with `_is_signed=True` and `_bits=128`. The type check for the statement passes.
3. We call the `validate_modification` method on the definition object
for `foo` to confirm that it is a value that may be modified (not a constant).
4. Because the statement involves a mathematical operator, we also call the
`validate_numeric_op` method on `foo` to confirm that the operation is
allowed.

#### 3. Calling a builtin function

```python
bar: bytes32 = sha256(b"hash me!")
```

1. We look up `sha256` in `namespace` and retrieve the definition for the builtin
function.
2. We call `fetch_call_return` on the function definition object, with the AST
node representing the call. This method validates the input arguments, and returns
a `BytesM_T` with `m=32`.
3. We validation of the delcaration of `bar` in the same manner as the first
example, and compare the generated type to that returned by `sha256`.

### Exceptions

In general, the following list of exceptions is preferred for type-checking
errors. When more than one reason applies, the earliest exception in the list
takes precedence.

* `InvalidLiteral`: when no potential types can be found for an object
* `InvalidType`: a type mismatch involving a literal value.
* `TypeMismatch`: a type mismatch between two already-defined variables.
* `InvalidOperation`: attempting an invalid operation between two like types.
* `ImmutableViolation`: attempting to modify an immutable variable, constant, or definition.
* `StateAccessViolation`: violating the mutability of a function definition.
* `IteratorException`: improper use of iteration.

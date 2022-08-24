# 🐍 `vyper.semantics` 🐍

## Purpose

The `vyper.semantics` package performs syntax verification, type checking and semantics analysis of a
Vyper abstract syntax tree (AST).

## Organization

`vyper.semantics` has the following structure:

* [`types/`](types): Subpackage of classes and methods used to represent types
  * [`types/indexable/`](types/indexable)
    * [`mapping.py`](types/indexable/mapping.py): Mapping type
    * [`sequence.py`](types/indexable/sequence.py): Array and Tuple types
  * [`types/user/`](types/user)
    * [`interface.py`](types/user/interface.py): Contract interface types and getter functions
    * [`struct.py`](types/user/struct.py): Struct types and getter functions
  * [`types/value/`](types/value)
    * [`address.py`](types/value/address.py): Address type
    * [`array_value.py`](types/value/array_value.py): Single-value subscript types (bytes, string)
    * [`boolean.py`](types/value/boolean.py): Boolean type
    * [`bytes_fixed.py`](types/value/bytes_fixed.py): Fixed length byte types
    * [`numeric.py`](types/value/numeric.py): Integer and decimal types
  * [`abstract.py`](types/abstract.py): Abstract data type classes
  * [`bases.py`](types/bases.py): Common base classes for all type objects
  * [`event.py`](types/user/event.py): `Event` type class
  * [`function.py`](types/function.py): `ContractFunction` type class
  * [`utils.py`](types/utils.py): Functions for generating and fetching type objects
* [`validation/`](validation): Subpackage for type checking and syntax verification logic
  * [`base.py`](validation/base.py): Base validation class
  * [`local.py`](validation/local.py): Validates the local namespace of each function within a contract
  * [`module.py`](validation/module.py): Validates the module namespace of a contract.
  * [`utils.py`](validation/utils.py): Functions for comparing and validating types
* [`environment.py`](environment.py): Environment variables and builtin constants
* [`namespace.py`](namespace.py): `Namespace` object, a `dict` subclass representing the namespace of a contract

## Control Flow

The [`validation`](validation) subpackage contains the top-level `validate_semantics`
function. This function is used to verify and type-check a contract. The process
consists of three steps:

1. Preparing the builtin namespace
2. Validating the module-level scope
3. Validating local scopes

### 1. Preparing the builtin namespace

The [`Namespace`](namespace.py) object represents the namespace for a contract.
Builtins are added upon initialization of the object. This includes:

* Adding primitive type classes from the [`types/`](types) subpackage
* Adding environment variables and builtin constants from [`environment.py`](environment.py)
* Adding builtin functions from the [`functions`](../builtin_functions/functions.py) package
* Adding / resetting `self` and `log`

### 2. Validating the Module Scope

[`validation/module.py`](validation/module.py) validates the module-level scope
of a contract. This includes:

* Generating user-defined types (e.g. structs and interfaces)
* Creating type definitions for storage variables, user-defined constants, events
and functions
* Validating import statements and function signatures

### 3. Validating the Local Scopes

[`validation/local.py`](validation/local.py) validates the local scope within each
function in a contract. `FunctionNodeVisitor` is used to iterate over the statement
nodes in each function body and apply appropriate checks.

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

Type classes rely on inheritance to define their structure and functionlity.
Vyper uses three broad categories to represent types within the compiler.

#### Primitive Types

A **primitive type** (or just primitive) defines the base attributes of a given type.
There is only one primitive type object created for each Vyper type. All primitive
classes are subclasses of `BasePrimitive`.

Along with the builtin primitive types, user-defined ones may be created. These
primitives are defined in the modules within [`semantics/types/user`](types/user).
See the docstrings there for more information.

#### Type Definitions

A **type definition** (or just definition) is a type that has been assigned to a
specific variable, literal, or other value. Definition objects are typically derived
from primitives. They include additional information such as the constancy,
visibility and scope of the associated value.

A primitive type always has a corresponding type definition. However, not all
type definitions have a primitive type, e.g. arrays and tuples.

Comparing a definition to it's related primitive type will always evaluate `True`.
Comparing two definitions of the same class can sometimes evaluate false depending
on certain attributes. All definition classes are subclasses of `BaseTypeDefinition`.

Additionally, literal values sometimes have multiple _potential type definitions_.
In this case, a membership check determines if the literal is valid by comparing
the list of potential types against a specific type.

#### Abstract Types

An **abstract type** is an inherited class shared by two or more definition
classes. Abstract types do not implement any functionality and may not be directly
assigned to any values. They are used for broad type checking, in cases where
e.g. a function expects any numeric value, or any bytes value. All abstract type
classes are subclasses of `AbstractDataType`.

### Namespace

[`namespace.py`](namespace.py) contains the `Namespace` object. `Namespace` is a
`dict` subclass representing the namespace of a contract. It imposes several
additional restrictions:

* Attempting to replace an existing field raises `NamespaceCollision`
* Attempting to access a key that does not exist raises `UndeclaredDefinition`

To ensure that only one copy of `Namespace` exists throughout the package, you
should access it using the `get_namespace` method:

```python
from brownie.context.namespace import get_namespace

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

* Primitive type objects include one or both of `from_annotation` and `from_literal`
methods, which validate an AST node and a produce definition object
* Definition objects include a variety of `get_<thing>` and `validate_<action>` methods,
which are used to validate interactions and obtain new types based on AST nodes

All possible methods for primitives and definitions are outlined within the base
classes in [`types/bases.py`](types/bases.py). The functionality within the methods
of the base classes is typically to raise and give a meaningful explanation
for _why_ the syntax not valid.

Here are some examples:

#### 1. Declaring a Variable

```python
foo: int128
```

1. We look up `int128` in `namespace`. We retrieve an `Int128Primitive` object.
2. We call `Int128Primitive.from_annotation` with the AST node of the statement. This
method validates the statement and returns an `Int128Definition` object.
3. We store the new definition under the key `foo` within `namespace`.

#### 2. Modifying the value of a variable

```python
foo += 6
```

1. We look up `foo` in `namespace` and retrieve the `Int128Definition`.
2. We call `get_potential_types_from_node` with the target node
and are returned a list of types that are valid for the literal `6`. In this
case, the list includes `Int128Definition`. The type check for the statement
passes.
3. We call the `validate_modification` method on the definition object
for `foo` to confirm that it is a value that may be modified (not a constant).
4. Because the statement involves a mathematical operator, we also call the
`validate_numeric_operation` method on `foo` to confirm that the operation is
allowed.

#### 3. Calling a builtin function

```python
bar: bytes32 = sha256(b"hash me!")
```

1. We look up `sha256` in `namespace` and retrieve the definition for the builtin
function.
2. We call `fetch_call_return` on the function definition object, with the AST
node representing the call. This method validates the input arguments, and returns
a `Bytes32Definition`.
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

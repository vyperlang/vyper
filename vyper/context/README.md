# 🐍 `vyper.context` 🐍

## Purpose

The `vyper.context` package performs syntax verification and type checking of a
Vyper abstract syntax tree (AST).

## Organization

`vyper.context` has the following structure:

* [`types/`](types): Subpackage of classes and methods used to represent types
  * [`types/indexable/`](types/indexable)
    * [`bases.py`](types/indexable/bases.py): Inexable base types
    * [`mapping.py`](types/indexable/mapping.py): Mapping type
    * [`sequence.py`](types/indexable/sequence.py): Array and Tuple types
  * [`types/meta/`](types/meta)
    * [`interface.py`](types/meta/interface.py): Contract interface types and getter functions
    * [`struct.py`](types/meta/struct.py): Struct types and getter functions
  * [`types/value/`](types/value)
    * [`address.py`](types/value/address.py): Address type
    * [`array_value.py`](types/value/array_value.py): Single-value subscript types (bytes, string)
    * [`bases.py`](types/value/bases.py): `ValueType` base class
    * [`boolean.py`](types/value/boolean.py): Boolean type
    * [`bytes_fixed.py`](types/value/bytes_fixed.py): Fixed length byte types
    * [`numeric.py`](types/value/numeric.py): Integer and decimal types
  * [`bases.py`](types/bases.py): Common base classes for all type objects
  * [`event.py`](types/event.py): `Event` type class
  * [`function.py`](types/function.py): `ContractFunctionType` type class
  * [`utils.py`](types/utils.py): Functions for generating and fetching type objects
* [`validation/`](validation): Subpackage for type checking and syntax verification logic
  * [`base.py`](validation/base.py): Base validation class
  * [`local.py`](validation/local.py): Validates the local namespace of each function within a contract
  * [`module.py`](validation/module.py): Validates the module namespace of a contract.
  * [`utils.py`](validation/utils.py): Functions for comparing and validating types
* [`environment.py`](environment.py):
* [`namespace.py`](namespace.py): `Namespace` object, a `dict` subclass representing the namespace of a contract
* [`utils.py`](utils.py): Misc. functionality related to validation and comparison

## Control Flow

The [`validation`](validation) subpackage contains the top-level `validate_semantics`
function. This function is used to verify and type-check a contract. The process
consists of three steps:

1. Preparing the builtin namespace
2. Validating the module-level scope
3. Validating local scopes

### 1. Preparing the builtin namespace

The [`Namespace`](namespace.py) object represents the namespace for a contract.
Prior to beginning type checking, builtins are added via the `Namespace.enter_builtin_scope`
method. This includes:

* Adding pure type classes from the [`types/`](types) subpackage
* Adding environment variables and builtin constants from `environment.py`[environment.py]
* Adding builtin functions from the [`functions`](../functions/functions.py) package
* Adding / resetting `self` and `log`

### 2. Validating the Module Scope

[`validation/module.py`](validation/module.py) validates the module-level scope
of a contract. This includes:

* Generating user-defined pure types (e.g. structs and interfaces)
* Creating castable types for storage variables, user-defined constants, events
and functions
* Validating import statements and function signatures

### 3. Validating the Local Scopes

[`validation/local.py`](validation/local.py) validates the local scope within each
function in a contract. `FunctionNodeVisitor` is used to iterate over the statement
nodes in each function body and apply appropriate checks.

To learn more about the checks on each node type, read the docstrings on the methods
of `FunctionNodeVisitor`.

## Design

### Types

All type classes are found within the [`context/types/`](types) subpackage.

Type classes rely on inheritance to define their structure and functionlity.
Vyper uses three broad categories to represent types within the compiler.

#### Pure Types

A **pure type** defines the base attributes of a given type. There is only one pure
type object created for each Vyper type. All pure type classes are subclasses of
`BasePureType`.

Along with the builtin pure types, user-defined ones may be created. These types
are defined in the modules within [`context/types/meta`](types/meta). See
the docstrings there for more information.

#### Castable Types

A **castable type** is a type that has been assigned to a variable, literal, or
other value. Castable types are typically derived from pure types. They include
additional information such as the constancy, visibility and scope of the associated
value.

A pure type always has a corresponding castable type. However, not all castable types
have a pure type, e.g. arrays and tuples.

Comparing a castable type to it's related pure type will always evaluate true.
Comparing two castabled types of the same class can sometimes evaluate false depending
on certain attributes. All castable type classes are subclasses of `BaseType`.

Additionally, literal values sometimes have multiple _potential types_. In this case,
a membership check determines if the literal is valid by comparing the list of potential
types against an explicitely casted type.

#### Abstract Types

An **abstract type** is an inherited class shared by two or more castable type
classes. Abstract types may not be directly assigned to any values. They are used
for broad type checking, in cases where e.g. a function expects any numeric value,
or any bytes value.  All abstract type classes are subclasses of `AbstractDataType`.

### Namespace

[`namespace.py`](namespace.py) contains the `Namespace` object. `Namespace` is a
`dict` subclass representing the namespace of a contract. It imposes several
additional restrictions:

* Attempting to replace an existing field raises `NamespaceCollision`
* Attempting to access a key that does not exist raises `UndeclaredDefinition`

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

Prior to beginning type checking, the first scope **must** be initiated using
`Namespace.enter_builtin_scope`. This ensures that all builtin objects have
been added, and resets the content of `self` and `log`.

#### Importing the Namespace Object

The `namespace` module replaces itself with an instance of `Namespace` within
`sys.modules`. provides an easy way for other modules to import the same
`Namespace` object and ensures that only one copy of the object exists.

To access the `Namespace` object from another module:

```python
from vyper.context import namespace
```

Guido van Rossum provides an explanation of why this works in this post from the
[Python mailing list](https://mail.python.org/pipermail/python-ideas/2012-May/014969.html).

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
5. A new castable type `int128[2]` is added to the namespace with the name `foo`.

#### Exceptions

In general, the following list of exceptions is preferred for type-checking
errors. When more than one reason applies, the earliest exception in the list
takes precedence.

* `InvalidLiteral`: when no potential types can be found for an object
* `InvalidType`: a type mismatch involving a literal value.
* `TypeMismatch`: a type mismatch between two already-defined variables.
* `InvalidOperation`: attempting an invalid operation between two like types.
* `ConstancyViolation`: attempting to modify a constant.

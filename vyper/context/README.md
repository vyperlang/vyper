# 🐍 `vyper.context` 🐍

## Purpose

The `vyper.context` package performs syntax verification and type checking of a
Vyper abstract syntax tree (AST).

## Organization

`vyper.context` has the following structure:

* [`definitions`](definitions): Subpackage of classes and methods used to represent
definitions.
  * [`annotation_declaration.py`](definitions/annotation_declaration.py):
  Special definition classes that are declared in the annotation field of an assignment.
  * [`bases.py`](definitions/bases.py): Inherited base definition classes.
  * [`builtin_functions.py`](definitions/builtin_functions.py): Definition
  classes for builtin functions.
  * [`contract_functions.py`](definitions/contract_functions.py): Classes and functions
  for creating user-defined function definitions.
  * [`utils.py`](definitions/utils.py): Definition getter functions.
  * [`values.py`](definitions/values.py): Classes and functions for creating
  value definitions (variables and literals).
* [`types`](types): Subpackage of classes and methods used to represent types.
  * [`types/bases`](types/bases): Subpackage of inherited type base classes.
    * [`data.py`](types/bases/data.py): Inherited base classes defining
    the data format represented by a type.
    * [`structure.py`](types/bases/structure.py): Inherited base classes
    defining the allowable structure of a type.
  * [`builtins.py`](types/builtins.py): Builtin type classes.
  * [`union.py`](types/union.py): `UnionType` class, used for literals where the
  final type is not yet determined.
  * [`user_defined.py`](types/user_defined.py): Classes for user-defined types
  such as structs and interfaces.
  * [`utils.py`](types/utils.py): Type getter and helper functions.
* [`validation`](validation): Subpackage for type checking and syntax verification
logic.
  * [`builtins.py`](validation/builtins.py): Creates the builtin namespace.
  * [`local.py`](validation/local.py): Validates the local namespace of each
  function within a contract.
  * [`module.py`](validation/module.py): Validates the module namespace of
  a contract.
* [`namespace.py`](namespace.py): `Namespace` object, a `dict` subclass representing
the namespace of a contract.
* [`utils.py`](utils.py): Misc. functionality related to validation and comparison.

## Key Concepts

### Types and Definitions

A **type** is a set of attributes which tell the compiler how an object may be used.
Types place constraints on how different sets of data may be represented and interact
with one another.

A **definition** is a user-defined object (such as a variable, literal, or function)
which has one or more types. Depending on the underlying type(s), a definition can
take many different shapes.

In the following example, `foo` is a definition and `int128` is a type:

```python
foo: int128
```

Vyper is **strongly typed**. This means:

* Definitions cannot be created without an explicitly declared type.
* The type of an existing definition cannot be modified.
* Most operations cannot be performed between dislike types.

### Type Checking

Type checking involves a statement-by-statment evaluation of a contract. The
general process is:

1. Generate or retrieve definition objects for each value.
2. Validate that the syntax used is allowable for each definition.
3. Compare the types.

Validation of assignments happens right to left. In the following example:

```python
foo: int128 = -42
```

1. A new literal definition object is created for `42`. Based on the value, this
definition is given an implicit type `int128`.
2. A new reference definition object is created for `foo`. This definition has an
explicitly defined type of `int128`.
3. A comparison is performed between the types of the two definitions. The types
are compatible, so the statement is deemed valid.

## Control Flow

The [`validation`](validation) subpackage contains the top-level `validate_semantics`
function. This function is used to verify and type-check a contract. The process
consists of three steps:

1. Adding builtin types and definitions
2. Validating the module-level scope
3. Validating local scopes

### 1. Adding Builtins

[`validation/builtins.py`](validation/builtins.py) adds builtin types and
definitions to the namespace. This includes:

* Instantiating builtin type objects from [`types/builtins.py`](types/builtins.py)
* Instantiating metatype objects from [`types/user_defined.py`](types/user_defined.py)
* Instantiating builtin function definitions from
[`definitions/builtin_functions.py`](definitions/builtin_functions.py)
* Generating definition objects for environment variables and builtin constants
* Replacing references to builtin constants with literal values

### 2. Validating the Module Scope

[`validation/module.py`](validation/module.py) validates the module-level scope
of a contract. This includes:

* Using metatypes to generate user defined types (e.g. structs and interfaces)
* Generating definition objects for storage variables, user-defined constants,
events and functions
* Replacing references to user-defined constants with literal values
* Validating import statements and function signatures

Constant folding (handled with the [`ast.folding`](../ast/folding.py) module)
occurs twice during this phase. Once at the start, and again at the end after
user-defined constants have been replaced.

### 3. Validating the Local Scopes

[`validation/local.py`](validation/local.py) validates the local scope within each
function in a contract. `FunctionNodeVisitor` is used to iterate over the statement
nodes in each function body and apply appropriate checks.

To learn more about the checks on each node type, view `FunctionNodeVisitor` method
docstrings.

## Design

### Namespace

[`namespace.py`](namespace.py) contains the `Namespace` object. `Namespace` is a
`dict` subclass representing the namespace of a contract. It imposes several
additional restrictions:

* Attempting to replace an existing field raises `NamespaceCollision`
* Attempting to access a key that does not exist raises `UndeclaredDefinition`

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

#### Namespace as a Context Manager

`Namespace` can be used as a
[context manager](https://docs.python.org/3/reference/datamodel.html#with-statement-context-managers)
with the `enter_scope` method. Values added while inside the context are removed
when the context is exited.

```python
with namespace.enter_scope():
    namespace['foo'] = 42

namespace['foo']  # this raises an UndeclaredDefinition
```

### Types

Each Vyper type is represented by an object. There are two broad categories
of Vyper types:

* **Builtin** types are a core part of the Vyper language. They cannot be modified
by the user. Classes that define builtin types are found in
[`types/builtins.py`](types/builtins.py).
* **User-defined** types are defined within a Vyper contract. Classes that define
the permitted structure of each user-defined type are found in
[`types/user_defined.py`](types/user_defined.py).

#### Type Base Classes

Type classes rely on inheritance to define their structure and functionlity.
There are two categories of base classes to inherit from:

* [`types/bases/data.py`](types/bases/data.py) contains base **data** classes.
These classes determine the sort of data that a Vyper type may represent. Every
builtin type class must inherit exactly one data base class.
* [`types/bases/structure.py`](types/bases/structure.py) contains base **structure**
classes. These classes define the allowable structures that can be used to
represent a type. Every type class must inherit one or more structure base classes.

Depending on the inherited base classes, each type class then uses class attributes
to fine-tune it's specific structure.

For example, here is the `BoolType` class:

```python
class BoolType(BoolBase, ValueType):
    _id = "bool"
    _as_array = True
    _valid_literal = vy_ast.NameConstant
```

The inherited classes `BoolBase` (a data class) and `ValueType` (a structure class)
provide a broad structure for the final type. This structure is then refined with
the following attributes:

* `_id` sets the name the type is given within the namespace. In this case, `bool`.
* `_as_array` indicates that the type may be used as an array (e.g. `bool[2]`)
* `_valid_literal` sets the type(s) of AST node that may represent a literal value
of this type.

The specific functionality and relevant class attributes for each type are outlined
in the docstrings of each base class.

#### Metatypes

Metatypes are classes that allow creation of user-defined types. A Metatype class
must include a `get_type` method which returns a type object.

See the docstrings and existing classes in [`types/user_defined.py`](types/user_defined.py)
to learn more about metatypes.

#### UnionType

`UnionType` is a special type used for literal values when the final type is
not yet determined. It is a subclass of `set`.

When a `UnionType` is compared to another type, invalid types for the comparison
are removed. For example, the literal `1` initially has a `UnionType` of
`{int128, uint256}`. If the type is then compared to `-1` it is now considered to
be `int128`. Subsequent comparisons to `uint256` will raise.

`UnionType` is particularly useful when handling for loops. Consider the following
example:

```python
foo: int128 = 0
bar: uint256 = 0

for i in [1, 2, 3]:
    foo += i
    bar += i
```

1. A definition for `foo` is created with type `int128`.
2. A definition for `bar` is created with type `uint256`.
3. A definition for `i` is created. Because no type is explicitly declared, `i` is
given a `UnionType` of `{int128, uint256}` based on the values of the literal array.
4. The types `foo` and `i` are compared. The `UnionType` collapses to an `int128`.
5. The types of `bar` and `i` are compared. Because of the previous comparison `i`
is known to be type `int128`, so a `TypeMismatch` is raised.

### Definitions

Each definition is represented by an object. Definition classes are created
dynamically based on the type and value they represent, and the syntax with which
they are declared.

There are many possible definition types, however all definitions broadly fit
under two categories.

* **Value** definitions have a value, a type associated with that value.
* **Callable** definitions have no value, zero or more input types, zero or more
output types, and a method for call validation.

Because of the dynamic creation of definition classes, it is possible to create a
definition which is both a value *and* callable.

#### Value Definitions

Value definitions are typically composed of one of two base classes:

* `Literal`: For literals, where an exact value is known
* `Reference`: For variables or other references where the value may be unknown

This class then inherits any number of base classes which introduce specific
functionality. The final parent is always `BaseDefinition`.

The `build_value_definition` function handles dynamic creation of value definition
objects based on a set of AST nodes. The `from_type` classmethod in `Literal` or
`Reference` is used when a specific base class is requried.

Classes and functions related to value definitions can be found in
[`definitions/values.py`](definitions/values.py).

#### Callable Definitions

Callable definitions are used to represent anything which is callable, e.g. builtin
functions, contract functions, interfaces, events, etc.

Callable definitions do not have a type. Instead, they implement the
`fetch_call_return` method. This method validates a set of call argument AST nodes
and returns zero or more value definition objects.

Builtin functions may also include an `evaluate` method, used for constant folding
when the given call args are literals.

#### Annotation Declaration Definitions

Annotation declaration definitions are special definition objects which are declared
in the annotation field of an `AnnAssign` node. For example, `map`:

```python
foo: map(int128, address)
```

See the docstrings in [`definitions/annotation_declaration.py`](definitions/annotation_declaration.py)
to learn more about creating definitions which are declarable via assignment
annotations.

## Integration

...

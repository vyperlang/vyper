Compiler Notes
**************


Vyper Compilation Stages
========================

- Python AST
- Python AST to Vyper AST
- Vyper AST to LLL
- LLL to Bytecode


Differences from Python
=======================

Introduction
~~~~~~~~~~~~

As Vyper targets Smart Contract development - there are some notable differences. This section
aims to highlight the important parts.

Types
~~~~~

One of the key difference between Python and Vyper is that Python usese dynamic typing; and Vyper
uses static Typing. Type in Vyper are declared using Python Annotations e.g. `a: auint256`.

Types in the compiler are represented by the follwing Classes:

- NodeType
 - BaseType: Base type represented by standard 32 bytes word.
   - Supports any sub 32 type: address, uint32, int128
 - ContractType: BaseType('address')
- ByteArrayLike: Dyanmic bytes/strings usese len prefix string, as defined by the ABI.
 - StringType
 - ByteArrayTypes
- TupleLike: Represents any compound encoded types.
  - StructType
  - TupleType

Global Namespace
~~~~~~~~~~~~~~~~

- Predefined mappings, custom units used in the contract, interface imports (with
  interface application), events, and public & private function defintions are all placed at the first level
  of the python file (ast.Module).

*Storage & Mapping defintion*

Mappings and global variables are defined at the ast.Module base of the file. The defined globals
storage types are accessible with public and private functions using the builtin `self.` keyword.

When declaring a global a `public()` can create a getter function for the value. e.g.
`a: public(uint256)`.

*Events / Logging*

Events are defined using the Annotation of a ast.Call with a name of `event`.

```
Transfer: event({_from: indexed(address), _to: indexed(address), _value: uint256})
```

The `event` takes a single argument of `ast.Dict` with optional `indexed` around the specific types -
which indicates wether a topic is index or not (see the LOG opcode).

*Interfaces / Interface Definitions *

Interfaces can be imported from external files as well defined locally within a contract using the
`contract` keyword.


Unsupported python statements and expressions
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

- `yield`
- `async`
- `await`
- `lambda` functions
- bitwise shifting operators
  - The use of bitwise shiftiing operators is not supported, instead `bitewise_*` functions exist.
- shifting operators not supported. Use `shift` insetad.
- floor division operator `//` is not supported. Use `floor` and `ceil` instead, to make rounding
  operations clear.

Statements
~~~~~~~~~~

*Simple Statements*

**Airthmetic Conversions**

Vyper enforces airthmetic conversions, to be explicit vs. python which uses implicit type conversion.
This was chosen specifically, to make the conversion steps clearer. The expression `1 * 1.0` will
be disallowed, instead `convert(1, decimal) * 1.0`.

**Identifiers**

Vyper ensures variables names can only consist of alphanumeric characters, with `_`. The specific
regex tested against is `^[_a-zA-Z][a-zA-Z0-9_]*$`.

**Literals**

Vyper has support for integer, decimal, string and byte python literals.
- If to Literals are found in an expression they are constant folded.
  - `10*10` will be converted to `100`
  - However `10*10*a` will not be converted.
- See above artihmetic onversion rules.
- There are limitations to byte & string literals based on their usage.
  - e.g. A string literal of size 100 can't be assigned or return to an annoted size of 32.
- To distinguish between `int128` and `uint256` literals Vyper uses the following ruleset.
  - If literal int value is above MAXNUM (2**127 - 1), literal is a uint256.
  - If literal int value is under MINNUM (-2**127), literal is invalid.
  - If assignment of literal to a known type (could be uint256 or int128), use appropriate type.
  - Consequently slightly confusing error message of `Cannot assign uint256 to int128` does occur,
    but seemed to be a reasonable trade off (don't have to convert(xxxx, uint256) on assingment).

**Comparisons / Boolean Operations*

- Comparisons
  - As long as all members of are of the same type -comparisons are supported.
- Boolean `and`, `or` operations are supported.
    - Currently not short-circuited (VIP pending)

** Membership **

- Array membership e.g. `assert a in self.owners` is supported.

*Compound Statements*

**Functions**

- Function Annotations are forced, as Vyper is statically typed.
- Inline (or inline private) functions are not permitted, this could lead to confusion,
  especially with regards to scoping (naming the inline function the same as another global
  function), therefore this should be disallowed:

```
@public
def test() -> uint256:
   def subtest() -> uint256:
      return 1
   return subtest()
```

- All function require either a `@public` or `@private` decorator.
- Option decorator for locking a function call against re-entrancy: `@nonreentrant`.

**For Statements**

- Vyper uses very restrictive `for` statements, this is to minimise gas limiting attacks.
  The specific types of `for` loops that are supported are:
  1.) `for i in list_variable`.
  2.) `for i in range(10)`
  3.) `for i in range(0, 100)`
  4.) `for i in range(x, x + 10)`
  As can be seen all these have been picked to ensure execution of a finite number of steps.


Expressions
~~~~~~~~~~~


Unit System
~~~~~~~~~~~

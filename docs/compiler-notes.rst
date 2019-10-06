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


Global Namespace
~~~~~~~~~~~~~~~~

- Predefined mappings, custom units used in the contract, interface imports (with
  interface application), events, and public & private function defintions are all placed at the first level
  of the python file (ast.Module).

*Storage & Mapping defintion*

Mappings and global variables are defined at the ast.Module base of the file. The defined globals
storage types are accessible with public and private functions using the builtin `self.` keyword.

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


*Compound Statements*

**Functions**

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

Expressions
~~~~~~~~~~~


Unit System
~~~~~~~~~~~

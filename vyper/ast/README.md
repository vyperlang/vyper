# 🐍 `vyper.ast` 🐍

## Purpose

The `vyper.ast` module handles the conversion of Vyper source code into an abstract
syntax tree (AST). It also contains functionality for traversing and modifying the AST,
and parsing NatSpec docstrings.

## Organization

`vyper.ast` has the following structure:

* [`annotation.py`](annotation.py): Contains the `AnnotatingVisitor` class, used to
annotate and modify the Python AST prior to converting it to a Vyper AST.
* [`natspec.py`](natspec.py): Functions for parsing NatSpec docstrings within the
source.
* [`nodes.py`](nodes.py): Contains the Vyper node classes, and the `get_node`
function which generates a Vyper node from a Python node.
* [`pre_parser.py`](pre_parser.py): Functions for converting Vyper source into
parseable Python source.
* [`utils.py`](utils.py): High-level functions for converting source code into AST
nodes.

## Control Flow

### Node Generation

`vyper.ast.utils.parse_to_ast` is the main function used to generate a Vyper AST
from a source string. The process is as follows:

1. In [`pre_parser.py`](pre_parser.py), Vyper source is modified into parseable
Python. This primarily involves substituting out `contract` and `struct` statements
for `class`.
2. A Python AST is generated from the modified source.
3. In [`annotation.py`](annotation.py), additional information is added to the
Python AST, and some nodes are modified to aid conversion to the Vyper AST.
4. In [`nodes.py`](nodes.py), the modified Python AST nodes are converted to Vyper
AST nodes.

Conversion between a Python Node and a Vyper Node uses the following rules:

* The type of Vyper node is determined from the `ast_type` field of the Python node.
* Fields listed in `__slots__` may be included and may have a value.
* Fields listed in `_translated_fields` have their key modified prior to being added.
This is used to handle discrepancies in how nodes are structured between different
Python versions.
* Fields listed in `_only_empty_fields`, if present within the Python AST, must
be `None` or a `SyntaxException` is raised.
* All other fields are ignored.

Most Vyper nodes have an identical (or simplified) structure to their Python
counterpart. Divergences are always handled in a Vyper node's `__init__` method,
and explained in the docstring. To learn more about the structure of the nodes:

* Green Tree Snakes: [Meet the Nodes](https://greentreesnakes.readthedocs.io/en/latest/nodes.html)

### Traversing the AST

Each node contains several methods that are used to traverse the AST. These methods
can optionally include one or more filters in order to quickly search for children
or parents that match a desired pattern.

* `get_children`: Returns a list of children of the given node.
* `get_descendants`: Returns a list of descendants of the given node.
* `get_ancestor`: Returns the parent or an ascendant of the given node.
* `get`: Recursive getter function for node attributes.

To learn more about these methods, read their docstrings in the `VyperNode` class
in [`nodes.py`](nodes.py).

## Design

### `__slots__`

Node classes in make use of `__slots__` for additional type safety. Denying the
creation of `__dict__` in node classes ensures that unwanted fields cannot be
silently included in the nodes.

To learn more about `__slots__`:

* Python Documentation: [`__slots__`](https://docs.python.org/3.10/reference/datamodel.html#slots)
* Stack Overflow: [Usage of `__slots__`?](https://stackoverflow.com/a/28059785/11451521)

### Interface Files (`.pyi`)

This module makes use of Python interface files ("stubs") to aid in MyPy type
annotation.

Stubs share the same name as their source counterparts, with a `.pyi` extension.
Whenever included, a stub takes precedence over a source file. For example, given
the following file structure:

```bash
ast/
  node.py
  node.pyi
```

The type information in `node.pyi` is applied to `node.py`. Any types given in
`node.py` are only included to aid readability - they are ignored by the type
checker.

You must modify both the source file and the stub when you make changes to a source
file with a corresponding stub.

The following resources are useful for familiarizing yourself with stubs:

* [MyPy: Stub Files](https://mypy.readthedocs.io/en/stable/stubs.html)
* [PEP 484: Stub Files](https://www.python.org/dev/peps/pep-0484/#stub-files)

## Integration

All node classes are imported from `ast/nodes.py` into `ast/__init__.py`. If you
are importing an AST node from another module, you should do so from the root `ast`
package.

For readability, `ast` should always be aliased as `vy_ast`.

```python
# Good
from vyper import ast as vy_ast
from vyper.ast import VyperNode

# Bad - could be mistaken for the builtin ast library
from vyper import ast

# Bad - only the functionality within vyper.ast is considered "public"
from vyper.ast import nodes
from vyper.ast.nodes import VyperNode
```

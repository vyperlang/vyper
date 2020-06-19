"""
isort:skip_file
"""
import sys

from . import nodes, validation  # noqa: F401
from .nodes import compare_nodes  # noqa: F401
from .utils import ast_to_dict, parse_to_ast  # noqa: F401
from .natspec import parse_natspec  # noqa: F401

# adds vyper.ast.nodes classes into the local namespace
for name, obj in (
    (k, v)
    for k, v in nodes.__dict__.items()
    if type(v) is type and nodes.VyperNode in v.__mro__
):
    setattr(sys.modules[__name__], name, obj)


# required to avoid circular dependency
from . import folding  # noqa: F401, E402

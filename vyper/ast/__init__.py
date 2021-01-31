"""
isort:skip_file
"""
import sys

from . import nodes, validation
from .natspec import parse_natspec
from .nodes import compare_nodes
from .utils import ast_to_dict, parse_to_ast

# adds vyper.ast.nodes classes into the local namespace
for name, obj in (
    (k, v) for k, v in nodes.__dict__.items() if type(v) is type and nodes.VyperNode in v.__mro__
):
    setattr(sys.modules[__name__], name, obj)


# required to avoid circular dependency
from . import expansion, folding  # noqa: E402

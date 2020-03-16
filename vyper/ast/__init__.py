import sys

from . import nodes
from .utils import (  # noqa: F401
    ast_to_dict,
    parse_to_ast,
)

# adds vyper.ast.nodes classes into the local namespace
for name, obj in (
    (k, v) for k, v in nodes.__dict__.items() if
    type(v) is type and nodes.VyperNode in v.__mro__
):
    setattr(sys.modules[__name__], name, obj)

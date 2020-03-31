import sys

from . import (  # noqa: F401
    folding,
    nodes,
)
from .nodes import (  # noqa: F401
    compare_nodes,
)
from .utils import (  # noqa: F401
    ast_to_dict,
    parse_to_ast,
)

from .natspec import (  # noqa: F401; isort:skip
    parse_natspec,
)

# adds vyper.ast.nodes classes into the local namespace
for name, obj in (
    (k, v) for k, v in nodes.__dict__.items() if
    type(v) is type and nodes.VyperNode in v.__mro__
):
    setattr(sys.modules[__name__], name, obj)

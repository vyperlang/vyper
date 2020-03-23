import re
from typing import (
    Optional,
    Tuple,
    Union,
)

from asttokens import (
    LineNumbers,
)

from vyper.ast import (
    nodes as vy_ast,
)
from vyper.exceptions import (
    NatSpecSyntaxException,
)
from vyper.parser.global_context import (
    GlobalContext,
)
from vyper.signatures import (
    sig_utils,
)
from vyper.typing import (
    InterfaceDict,
    InterfaceImports,
)

SINGLE_FIELDS = ("title", "author", "notice", "dev")
PARAM_FIELDS = ("param", "return")
USERDOCS_FIELDS = ("notice",)


def parse_natspec(
    vyper_ast: vy_ast.Module,
    interface_codes: Union[InterfaceDict, InterfaceImports, None] = None,
) -> Tuple[dict, dict]:
    """
    Parses NatSpec documentation from a contract.

    Arguments
    ---------
    vyper_ast : Module
        Module-level vyper ast node.
    interface_codes: Dict, optional
        Dict containing relevant data for any import statements related to
        this contract.

    Returns
    -------
    dict
        NatSpec user documentation
    dict
        NatSpec developer documentation
    """
    userdoc, devdoc = {}, {}
    source: str = vyper_ast.full_source_code

    global_ctx = GlobalContext.get_global_context(vyper_ast, interface_codes)

    docstring = vyper_ast.get("doc_string.value")
    if docstring:
        devdoc.update(_parse_docstring(source, docstring, ("param", "return")))
        if "notice" in devdoc:
            userdoc["notice"] = devdoc.pop("notice")

    for node in [i for i in vyper_ast.body if i.get("doc_string.value")]:
        docstring = node.doc_string.value
        sigs = sig_utils.mk_single_method_identifier(node, global_ctx)

        if isinstance(node.returns, vy_ast.Tuple):
            ret_len = len(node.returns.elts)
        elif node.returns:
            ret_len = 1
        else:
            ret_len = 0

        if sigs:
            args = tuple(i.arg for i in node.args.args)
            fn_natspec = _parse_docstring(source, docstring, ("title",), args, ret_len)
            for s in sigs:
                if "notice" in fn_natspec:
                    userdoc.setdefault("methods", {})[s] = {
                        "notice": fn_natspec.pop("notice")
                    }
                if fn_natspec:
                    devdoc.setdefault("methods", {})[s] = fn_natspec

    return userdoc, devdoc


def _parse_docstring(
    source: str,
    docstring: str,
    invalid_fields: Tuple,
    params: Optional[Tuple] = None,
    return_length: int = 0,
) -> dict:

    natspec: dict = {}
    if params is None:
        params = tuple()

    line_no = LineNumbers(source)
    start = source.index(docstring)

    translate_map = {
        "return": "returns",
        "dev": "details",
        "param": "params",
    }

    pattern = r"(?:^|\n)\s*@(\S+)\s*([\s\S]*?)(?=\n\s*@\S|\s*$)"

    for match in re.finditer(pattern, docstring):
        tag, value = match.groups()
        err_args = (source, *line_no.offset_to_line(start + match.start(1)))

        if tag not in SINGLE_FIELDS + PARAM_FIELDS:
            raise NatSpecSyntaxException(f"Unknown NatSpec field '@{tag}'", *err_args)
        if tag in invalid_fields:
            raise NatSpecSyntaxException(
                f"'@{tag}' is not a valid field for this docstring", *err_args
            )

        if not value or value.startswith("@"):
            raise NatSpecSyntaxException(f"No description given for tag '@{tag}'", *err_args)

        if tag not in PARAM_FIELDS:
            if tag in natspec:
                raise NatSpecSyntaxException(f"Duplicate NatSpec field '@{tag}'", *err_args)
            natspec[translate_map.get(tag, tag)] = " ".join(value.split())
            continue

        tag = translate_map.get(tag, tag)
        natspec.setdefault(tag, {})

        if tag == "params":
            try:
                key, value = value.split(maxsplit=1)
            except ValueError as exc:
                raise NatSpecSyntaxException(
                    f"No description given for parameter '{value}'", *err_args
                ) from exc
            if key not in params:
                raise NatSpecSyntaxException(f"Method has no parameter '{key}'", *err_args)

        elif tag == "returns":
            if not return_length:
                raise NatSpecSyntaxException(f"Method does not return any values", *err_args)
            if len(natspec["returns"]) >= return_length:
                raise NatSpecSyntaxException(
                    f"Number of documented return values exceeds actual number",
                    *err_args,
                )
            key = f"_{len(natspec['returns'])}"

        if key in natspec[tag]:
            raise NatSpecSyntaxException(
                f"Parameter '{key}' documented more than once", *err_args
            )
        natspec[tag][key] = " ".join(value.split())

    if not natspec:
        natspec["notice"] = " ".join(docstring.split())
    elif not docstring.strip().startswith("@"):
        raise NatSpecSyntaxException(
            "NatSpec docstring opens with untagged comment",
            source,
            *line_no.offset_to_line(start),
        )

    return natspec

import re
from typing import Optional, Tuple

from asttokens import LineNumbers

from vyper.ast import nodes as vy_ast
from vyper.exceptions import NatSpecSyntaxException

SINGLE_FIELDS = ("title", "author", "license", "notice", "dev")
PARAM_FIELDS = ("param", "return")
USERDOCS_FIELDS = ("notice",)


def parse_natspec(vyper_module_folded: vy_ast.Module) -> Tuple[dict, dict]:
    """
    Parses NatSpec documentation from a contract.

    Arguments
    ---------
    vyper_module_folded : Module
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
    from vyper.semantics.types.function import FunctionVisibility

    userdoc, devdoc = {}, {}
    source: str = vyper_module_folded.full_source_code

    docstring = vyper_module_folded.get("doc_string.value")
    if docstring:
        devdoc.update(_parse_docstring(source, docstring, ("param", "return")))
        if "notice" in devdoc:
            userdoc["notice"] = devdoc.pop("notice")

    for node in [i for i in vyper_module_folded.body if i.get("doc_string.value")]:
        docstring = node.doc_string.value
        func_type = node._metadata["type"]
        if func_type.visibility != FunctionVisibility.EXTERNAL:
            continue

        if isinstance(node.returns, vy_ast.Tuple):
            ret_len = len(node.returns.elements)
        elif node.returns:
            ret_len = 1
        else:
            ret_len = 0

        args = tuple(i.arg for i in node.args.args)
        invalid_fields = ("title", "license")
        fn_natspec = _parse_docstring(source, docstring, invalid_fields, args, ret_len)
        for method_id in func_type.method_ids:
            if "notice" in fn_natspec:
                userdoc.setdefault("methods", {})[method_id] = {"notice": fn_natspec.pop("notice")}
            if fn_natspec:
                devdoc.setdefault("methods", {})[method_id] = fn_natspec

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

    translate_map = {"return": "returns", "dev": "details", "param": "params"}

    pattern = r"(?:^|\n)\s*@(\S+)\s*([\s\S]*?)(?=\n\s*@\S|\s*$)"

    for match in re.finditer(pattern, docstring):
        tag, value = match.groups()
        err_args = (source, *line_no.offset_to_line(start + match.start(1)))

        if tag not in SINGLE_FIELDS + PARAM_FIELDS and not tag.startswith("custom:"):
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
                raise NatSpecSyntaxException("Method does not return any values", *err_args)
            if len(natspec["returns"]) >= return_length:
                raise NatSpecSyntaxException(
                    "Number of documented return values exceeds actual number", *err_args
                )
            key = f"_{len(natspec['returns'])}"

        if key in natspec[tag]:
            raise NatSpecSyntaxException(f"Parameter '{key}' documented more than once", *err_args)
        natspec[tag][key] = " ".join(value.split())

    if not natspec:
        natspec["notice"] = " ".join(docstring.split())
    elif not docstring.strip().startswith("@"):
        raise NatSpecSyntaxException(
            "NatSpec docstring opens with untagged comment", source, *line_no.offset_to_line(start)
        )

    return natspec

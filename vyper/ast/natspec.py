import re
from dataclasses import dataclass
from typing import Optional, Tuple

from vyper.ast import nodes as vy_ast
from vyper.exceptions import NatSpecSyntaxException

SINGLE_FIELDS = ("title", "author", "license", "notice", "dev")
PARAM_FIELDS = ("param", "return")
USERDOCS_FIELDS = ("notice",)


@dataclass
class NatspecOutput:
    userdoc: dict
    devdoc: dict


def parse_natspec(annotated_vyper_module: vy_ast.Module) -> NatspecOutput:
    try:
        return _parse_natspec(annotated_vyper_module)
    except NatSpecSyntaxException as e:
        e.resolved_path = annotated_vyper_module.resolved_path
        raise e


def _parse_natspec(annotated_vyper_module: vy_ast.Module) -> NatspecOutput:
    """
    Parses NatSpec documentation from a contract.

    Arguments
    ---------
    annotated_vyper_module: Module
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
    source: str = annotated_vyper_module.full_source_code

    if annotated_vyper_module.get("doc_string.value"):
        doc_node = annotated_vyper_module.doc_string
        devdoc.update(_parse_docstring(source, doc_node, ("param", "return")))
        if "notice" in devdoc:
            userdoc["notice"] = devdoc.pop("notice")

    for node in [i for i in annotated_vyper_module.body if i.get("doc_string.value")]:
        func_type = node._metadata["func_type"]
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
        fn_natspec = _parse_docstring(source, node.doc_string, invalid_fields, args, ret_len)
        for method_id in func_type.method_ids:
            if "notice" in fn_natspec:
                userdoc.setdefault("methods", {})[method_id] = {"notice": fn_natspec.pop("notice")}
            if fn_natspec:
                devdoc.setdefault("methods", {})[method_id] = fn_natspec

    return NatspecOutput(userdoc=userdoc, devdoc=devdoc)


# one source token of a (non-raw) string literal: a line continuation, an escape
# sequence, a `\r\n` line ending or a single character
_LITERAL_TOKEN = re.compile(
    r"\\\r?\n|\\N\{[^}]*\}|\\x[0-9a-fA-F]{2}|\\u[0-9a-fA-F]{4}|\\U[0-9a-fA-F]{8}"
    r"|\\[0-7]{1,3}|\\[\\'\"abfnrtv]|\r\n|.",
    re.DOTALL,
)
_RAW_LITERAL_TOKEN = re.compile(r"\r\n|.", re.DOTALL)


def _docstring_position(doc_node: vy_ast.Str, offset: int) -> Tuple[int, int]:
    # map an offset in the parsed docstring to a (line, column) in the source.
    # the parsed value can differ from the source text (escape sequences, line
    # continuations, `\r\n` line endings), so walk the raw string literal.
    raw = doc_node.node_source_code
    body = raw.lstrip("rRuU")
    quote_len = 3 if body[:3] in ('"""', "'''") else 1
    start = len(raw) - len(body) + quote_len
    content = raw[start : len(raw) - quote_len]

    is_raw = "r" in raw[: len(raw) - len(body)].lower()
    pattern = _RAW_LITERAL_TOKEN if is_raw else _LITERAL_TOKEN

    # source offset (within `content`) of each character of the parsed value
    content_offsets = []
    for match in pattern.finditer(content):
        token = match.group()
        if len(token) > 1 and token.startswith("\\") and not is_raw:
            # a line continuation adds nothing, any other escape one character
            length = 0 if token[1] in "\r\n" else 1
        else:
            length = 1
        content_offsets.extend([match.start()] * length)
    content_offsets.append(len(content))

    if len(content_offsets) == len(doc_node.value) + 1:
        pos = start + content_offsets[offset]
    else:  # pragma: nocover
        # unexpected literal form: fall back to the start of the docstring
        pos = start

    lineno = doc_node.lineno + raw.count("\n", 0, pos)
    if lineno == doc_node.lineno:
        return lineno, doc_node.col_offset + pos
    return lineno, pos - raw.rfind("\n", 0, pos) - 1


def _parse_docstring(
    source: str,
    doc_node: vy_ast.Str,
    invalid_fields: Tuple,
    params: Optional[Tuple] = None,
    return_length: int = 0,
) -> dict:
    natspec: dict = {}
    if params is None:
        params = tuple()

    docstring = doc_node.value

    translate_map = {"return": "returns", "dev": "details", "param": "params"}

    pattern = r"(?:^|\n)\s*@(\S+)\s*([\s\S]*?)(?=\n\s*@\S|\s*$)"

    for match in re.finditer(pattern, docstring):
        tag, value = match.groups()
        err_args = (source, *_docstring_position(doc_node, match.start(1)))

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
            "NatSpec docstring opens with untagged comment",
            source,
            *_docstring_position(doc_node, 0),
        )

    return natspec

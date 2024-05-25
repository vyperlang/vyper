import ast as python_ast
import tokenize
from decimal import Decimal
from typing import Any, Dict, List, Optional, Union

import asttokens

from vyper.ast import nodes as vy_ast
from vyper.ast.pre_parser import pre_parse
from vyper.compiler.settings import Settings
from vyper.exceptions import CompilerPanic, ParserException, SyntaxException
from vyper.typing import ModificationOffsets
from vyper.utils import sha256sum, vyper_warn


def parse_to_ast(*args: Any, **kwargs: Any) -> vy_ast.Module:
    _settings, ast = parse_to_ast_with_settings(*args, **kwargs)
    return ast


def parse_to_ast_with_settings(
    vyper_source: str,
    source_id: int = 0,
    module_path: Optional[str] = None,
    resolved_path: Optional[str] = None,
    add_fn_node: Optional[str] = None,
) -> tuple[Settings, vy_ast.Module]:
    """
    Parses a Vyper source string and generates basic Vyper AST nodes.

    Parameters
    ----------
    vyper_source: str
        The Vyper source code to parse.
    source_id : int, optional
        Source id to use in the `src` member of each node.
    contract_name: str, optional
        Name of contract.
    add_fn_node: str, optional
        If not None, adds a dummy Python AST FunctionDef wrapper node.
    source_id: int, optional
        The source ID generated for this source code.
        Corresponds to FileInput.source_id
    module_path: str, optional
        The path of the source code
        Corresponds to FileInput.path
    resolved_path: str, optional
        The resolved path of the source code
        Corresponds to FileInput.resolved_path

    Returns
    -------
    list
        Untyped, unoptimized Vyper AST nodes.
    """
    if "\x00" in vyper_source:
        raise ParserException("No null bytes (\\x00) allowed in the source code.")
    settings, class_types, for_loop_annotations, python_source = pre_parse(vyper_source)
    try:
        py_ast = python_ast.parse(python_source)
    except SyntaxError as e:
        # TODO: Ensure 1-to-1 match of source_code:reformatted_code SyntaxErrors
        raise SyntaxException(str(e), vyper_source, e.lineno, e.offset) from None

    # Add dummy function node to ensure local variables are treated as `AnnAssign`
    # instead of state variables (`VariableDecl`)
    if add_fn_node:
        fn_node = python_ast.FunctionDef(add_fn_node, py_ast.body, [], [])
        fn_node.body = py_ast.body
        fn_node.args = python_ast.arguments(defaults=[])
        py_ast.body = [fn_node]

    annotate_python_ast(
        py_ast,
        vyper_source,
        class_types,
        for_loop_annotations,
        source_id=source_id,
        module_path=module_path,
        resolved_path=resolved_path,
    )

    # postcondition: consumed all the for loop annotations
    assert len(for_loop_annotations) == 0

    # Convert to Vyper AST.
    module = vy_ast.get_node(py_ast)
    assert isinstance(module, vy_ast.Module)  # mypy hint

    return settings, module


def ast_to_dict(ast_struct: Union[vy_ast.VyperNode, List]) -> Union[Dict, List]:
    """
    Converts a Vyper AST node, or list of nodes, into a dictionary suitable for
    output to the user.
    """
    if isinstance(ast_struct, vy_ast.VyperNode):
        return ast_struct.to_dict()

    if isinstance(ast_struct, list):
        return [i.to_dict() for i in ast_struct]

    raise CompilerPanic(f'Unknown Vyper AST node provided: "{type(ast_struct)}".')


def dict_to_ast(ast_struct: Union[Dict, List]) -> Union[vy_ast.VyperNode, List]:
    """
    Converts an AST dict, or list of dicts, into Vyper AST node objects.
    """
    if isinstance(ast_struct, dict):
        return vy_ast.get_node(ast_struct)
    if isinstance(ast_struct, list):
        return [vy_ast.get_node(i) for i in ast_struct]
    raise CompilerPanic(f'Unknown ast_struct provided: "{type(ast_struct)}".')


def annotate_python_ast(
    parsed_ast: python_ast.AST,
    vyper_source: str,
    modification_offsets: ModificationOffsets,
    for_loop_annotations: dict,
    source_id: int = 0,
    module_path: Optional[str] = None,
    resolved_path: Optional[str] = None,
) -> python_ast.AST:
    """
    Annotate and optimize a Python AST in preparation conversion to a Vyper AST.

    Parameters
    ----------
    parsed_ast : AST
        The AST to be annotated and optimized.
    vyper_source: str
        The original vyper source code
    loop_var_annotations: dict
        A mapping of line numbers of `For` nodes to the tokens of the type
        annotation of the iterator extracted during pre-parsing.
    modification_offsets : dict
        A mapping of class names to their original class types.

    Returns
    -------
        The annotated and optimized AST.
    """
    tokens = asttokens.ASTTokens(vyper_source)
    assert isinstance(parsed_ast, python_ast.Module)  # help mypy
    tokens.mark_tokens(parsed_ast)
    visitor = AnnotatingVisitor(
        vyper_source,
        modification_offsets,
        for_loop_annotations,
        tokens,
        source_id,
        module_path=module_path,
        resolved_path=resolved_path,
    )
    visitor.visit(parsed_ast)

    return parsed_ast


class AnnotatingVisitor(python_ast.NodeTransformer):
    _source_code: str
    _modification_offsets: ModificationOffsets
    _loop_var_annotations: dict[int, dict[str, Any]]

    def __init__(
        self,
        source_code: str,
        modification_offsets: ModificationOffsets,
        for_loop_annotations: dict,
        tokens: asttokens.ASTTokens,
        source_id: int,
        module_path: Optional[str] = None,
        resolved_path: Optional[str] = None,
    ):
        self._tokens = tokens
        self._source_id = source_id
        self._module_path = module_path
        self._resolved_path = resolved_path
        self._source_code = source_code
        self._modification_offsets = modification_offsets
        self._for_loop_annotations = for_loop_annotations

        self.counter: int = 0

    def generic_visit(self, node):
        """
        Annotate a node with information that simplifies Vyper node generation.
        """
        # Decorate every node with the original source code to allow pretty-printing errors
        node.full_source_code = self._source_code
        node.node_id = self.counter
        node.ast_type = node.__class__.__name__
        self.counter += 1

        # Decorate every node with source end offsets
        start = (None, None)
        if hasattr(node, "first_token"):
            start = node.first_token.start
        end = (None, None)
        if hasattr(node, "last_token"):
            end = node.last_token.end
            if node.last_token.type == 4:
                # token type 4 is a `\n`, some nodes include a trailing newline
                # here we ignore it when building the node offsets
                end = (end[0], end[1] - 1)

        node.lineno = start[0]
        node.col_offset = start[1]
        node.end_lineno = end[0]
        node.end_col_offset = end[1]

        # TODO: adjust end_lineno and end_col_offset when this node is in
        # modification_offsets

        if hasattr(node, "last_token"):
            start_pos = node.first_token.startpos
            end_pos = node.last_token.endpos

            if node.last_token.type == 4:
                # ignore trailing newline once more
                end_pos -= 1
            node.src = f"{start_pos}:{end_pos-start_pos}:{self._source_id}"
            node.node_source_code = self._source_code[start_pos:end_pos]

        return super().generic_visit(node)

    def _visit_docstring(self, node):
        """
        Move a node docstring from body to `doc_string` and annotate it as `DocStr`.
        """
        self.generic_visit(node)

        if node.body:
            n = node.body[0]
            if (
                isinstance(n, python_ast.Expr)
                and isinstance(n.value, python_ast.Constant)
                and isinstance(n.value.value, str)
            ):
                self.generic_visit(n.value)
                n.value.ast_type = "DocStr"
                del node.body[0]
                node.doc_string = n.value

        return node

    def visit_Module(self, node):
        # TODO: is this the best place for these? maybe they can be on
        # CompilerData instead.
        node.path = self._module_path
        node.resolved_path = self._resolved_path
        node.source_sha256sum = sha256sum(self._source_code)
        node.source_id = self._source_id
        return self._visit_docstring(node)

    def visit_FunctionDef(self, node):
        if node.decorator_list:
            # start the source highlight at `def` to improve annotation readability
            decorator_token = node.decorator_list[-1].last_token
            def_token = self._tokens.find_token(decorator_token, tokenize.NAME, tok_str="def")
            node.first_token = def_token

        return self._visit_docstring(node)

    def visit_ClassDef(self, node):
        """
        Convert the `ClassDef` node into a Vyper-specific node type.

        Vyper uses `struct` and `interface` in place of `class`, however these
        values must be substituted out to create parseable Python. The Python
        node is annotated with the desired Vyper type via the `ast_type` member.
        """
        self.generic_visit(node)

        node.ast_type = self._modification_offsets[(node.lineno, node.col_offset)]
        return node

    def visit_For(self, node):
        """
        Visit a For node, splicing in the loop variable annotation provided by
        the pre-parser
        """
        annotation_tokens = self._for_loop_annotations.pop((node.lineno, node.col_offset))

        if not annotation_tokens:
            # a common case for people migrating to 0.4.0, provide a more
            # specific error message than "invalid type annotation"
            raise SyntaxException(
                "missing type annotation\n\n"
                "  (hint: did you mean something like "
                f"`for {node.target.id}: uint256 in ...`?)",
                self._source_code,
                node.lineno,
                node.col_offset,
            )

        # some kind of black magic. untokenize preserves the line and column
        # offsets, giving us something like `\
        # \
        # \
        #   uint8`
        # that's not a valid python Expr because it is indented.
        # but it's good because the code is indented to exactly the same
        # offset as it did in the original source!
        # (to best understand this, print out annotation_str and
        # self._source_code and compare them side-by-side).
        #
        # what we do here is add in a dummy target which we will remove
        # in a bit, but for now lets us keep the line/col offset, and
        # *also* gives us a valid AST. it doesn't matter what the dummy
        # target name is, since it gets removed in a few lines.
        annotation_str = tokenize.untokenize(annotation_tokens)
        annotation_str = "dummy_target:" + annotation_str

        try:
            fake_node = python_ast.parse(annotation_str).body[0]
        except SyntaxError as e:
            raise SyntaxException(
                "invalid type annotation", self._source_code, node.lineno, node.col_offset
            ) from e

        # fill in with asttokens info. note we can use `self._tokens` because
        # it is indented to exactly the same position where it appeared
        # in the original source!
        self._tokens.mark_tokens(fake_node)

        # replace the dummy target name with the real target name.
        fake_node.target = node.target
        # replace the For node target with the new ann_assign
        node.target = fake_node

        return self.generic_visit(node)

    def visit_Expr(self, node):
        """
        Convert the `Yield` node into a Vyper-specific node type.

        Vyper substitutes `yield` for non-pythonic statement such as `log`. Prior
        to generating Vyper AST, we must annotate `Yield` nodes with their original
        value.

        Because `Yield` is an expression-statement, we also remove it from it's
        enclosing `Expr` node.
        """
        self.generic_visit(node)

        if isinstance(node.value, python_ast.Yield):
            # CMC 2024-03-03 consider unremoving this from the enclosing Expr
            node = node.value
            node.ast_type = self._modification_offsets[(node.lineno, node.col_offset)]

        return node

    def visit_Await(self, node):
        start_pos = node.lineno, node.col_offset  # grab these before generic_visit modifies them
        self.generic_visit(node)
        node.ast_type = self._modification_offsets[start_pos]
        return node

    def visit_Call(self, node):
        # Convert structs declared as `Dict` node for vyper < 0.4.0 to kwargs
        if len(node.args) == 1 and isinstance(node.args[0], python_ast.Dict):
            msg = "Instantiating a struct using a dictionary is deprecated "
            msg += "as of v0.4.0 and will be disallowed in a future release. "
            msg += "Use kwargs instead e.g. Foo(a=1, b=2)"

            # add full_source_code so that str(VyperException(msg, node)) works
            node.full_source_code = self._source_code
            vyper_warn(msg, node)

            dict_ = node.args[0]
            kw_list = []

            assert len(dict_.keys) == len(dict_.values)
            for key, value in zip(dict_.keys, dict_.values):
                replacement_kw_node = python_ast.keyword(key.id, value)
                kw_list.append(replacement_kw_node)

            node.args = []
            node.keywords = kw_list

        self.generic_visit(node)

        return node

    def visit_Constant(self, node):
        """
        Handle `Constant` when using Python >=3.8

        In Python 3.8, `NameConstant`, `Num`, `Str`, and `Bytes` are deprecated
        in favor of `Constant`. To maintain consistency across versions, `ast_type`
        is modified to create the <=3.7 node classes.
        """
        if not isinstance(node.value, bool) and isinstance(node.value, (int, float)):
            return self.visit_Num(node)

        self.generic_visit(node)
        if node.value is None or isinstance(node.value, bool):
            node.ast_type = "NameConstant"
        elif isinstance(node.value, str):
            node.ast_type = "Str"
        elif isinstance(node.value, bytes):
            node.ast_type = "Bytes"
        elif isinstance(node.value, Ellipsis.__class__):
            node.ast_type = "Ellipsis"
        else:
            raise SyntaxException(
                "Invalid syntax (unsupported Python Constant AST node).",
                self._source_code,
                node.lineno,
                node.col_offset,
            )

        return node

    def visit_Num(self, node):
        """
        Adjust numeric node class based on the value type.

        Python uses `Num` to represent floats and integers. Integers may also
        be given in binary, octal, decimal, or hexadecimal format. This method
        modifies `ast_type` to separate `Num` into more granular Vyper node
        classes.
        """
        # modify vyper AST type according to the format of the literal value
        self.generic_visit(node)
        value = node.node_source_code

        # deduce non base-10 types based on prefix
        if value.lower()[:2] == "0x":
            if len(value) % 2:
                raise SyntaxException(
                    "Hex notation requires an even number of digits",
                    self._source_code,
                    node.lineno,
                    node.col_offset,
                )
            node.ast_type = "Hex"
            node.value = value

        elif value.lower()[:2] == "0b":
            node.ast_type = "Bytes"
            mod = (len(value) - 2) % 8
            if mod:
                raise SyntaxException(
                    f"Bit notation requires a multiple of 8 bits. {8-mod} bit(s) are missing.",
                    self._source_code,
                    node.lineno,
                    node.col_offset,
                )
            node.value = int(value, 2).to_bytes(len(value) // 8, "big")

        elif isinstance(node.value, float):
            node.ast_type = "Decimal"
            node.value = Decimal(value)

        elif isinstance(node.value, int):
            node.ast_type = "Int"

        else:  # pragma: nocover
            raise CompilerPanic(f"Unexpected type for Constant value: {type(node.value).__name__}")

        return node

    def visit_UnaryOp(self, node):
        """
        Adjust operand value and discard unary operations, where possible.

        This is done so that negative decimal literals are accurately represented.
        """
        self.generic_visit(node)

        is_sub = isinstance(node.op, python_ast.USub)
        is_num = hasattr(node.operand, "value") and isinstance(node.operand.value, (int, Decimal))
        if is_sub and is_num:
            node.operand.value = 0 - node.operand.value
            node.operand.col_offset = node.col_offset
            node.operand.node_source_code = node.node_source_code
            return node.operand
        else:
            return node

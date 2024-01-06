import ast as python_ast
import tokenize
from decimal import Decimal
from typing import Any, Dict, List, Optional, Union, cast

import asttokens

from vyper.ast import nodes as vy_ast
from vyper.ast.pre_parser import pre_parse
from vyper.compiler.settings import Settings
from vyper.exceptions import CompilerPanic, ParserException, SyntaxException
from vyper.typing import ModificationOffsets


def parse_to_ast(*args: Any, **kwargs: Any) -> vy_ast.Module:
    _settings, ast = parse_to_ast_with_settings(*args, **kwargs)
    return ast


def parse_to_ast_with_settings(
    source_code: str,
    source_id: int = 0,
    module_path: Optional[str] = None,
    resolved_path: Optional[str] = None,
    add_fn_node: Optional[str] = None,
) -> tuple[Settings, vy_ast.Module, dict[int, dict[str, Any]]]:
    """
    Parses a Vyper source string and generates basic Vyper AST nodes.

    Parameters
    ----------
    source_code : str
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
    if "\x00" in source_code:
        raise ParserException("No null bytes (\\x00) allowed in the source code.")
    settings, class_types, loop_var_annotations, reformatted_code = pre_parse(source_code)
    try:
        py_ast = python_ast.parse(reformatted_code)

        for k, v in loop_var_annotations.items():
            parsed_v = python_ast.parse(v["source_code"])
            loop_var_annotations[k]["parsed_ast"] = parsed_v
    except SyntaxError as e:
        # TODO: Ensure 1-to-1 match of source_code:reformatted_code SyntaxErrors
        raise SyntaxException(str(e), source_code, e.lineno, e.offset) from e

    # Add dummy function node to ensure local variables are treated as `AnnAssign`
    # instead of state variables (`VariableDecl`)
    if add_fn_node:
        fn_node = python_ast.FunctionDef(add_fn_node, py_ast.body, [], [])
        fn_node.body = py_ast.body
        fn_node.args = python_ast.arguments(defaults=[])
        py_ast.body = [fn_node]

    annotate_python_ast(
        py_ast,
        source_code,
        class_types,
        loop_var_annotations,
        source_id,
        module_path=module_path,
        resolved_path=resolved_path,
    )

    # Convert to Vyper AST.
    module = vy_ast.get_node(py_ast)
    assert isinstance(module, vy_ast.Module)  # mypy hint

    for k, v in loop_var_annotations.items():
        loop_var_vy_ast = vy_ast.get_node(v["parsed_ast"])
        loop_var_annotations[k]["vy_ast"] = loop_var_vy_ast
        del loop_var_annotations[k]["parsed_ast"]

    module._metadata["loop_var_annotations"] = loop_var_annotations

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


class AnnotatingVisitor(python_ast.NodeTransformer):
    _source_code: str
    _modification_offsets: ModificationOffsets

    def __init__(
        self,
        source_code: str,
        modification_offsets: Optional[ModificationOffsets],
        tokens: asttokens.ASTTokens,
        source_id: int,
        module_path: Optional[str] = None,
        resolved_path: Optional[str] = None,
    ):
        self._tokens = tokens
        self._source_id = source_id
        self._module_path = module_path
        self._resolved_path = resolved_path
        self._source_code: str = source_code
        self.counter: int = 0
        self._modification_offsets = {}
        if modification_offsets is not None:
            self._modification_offsets = modification_offsets

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
        start = node.first_token.start if hasattr(node, "first_token") else (None, None)
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
            if isinstance(n, python_ast.Expr) and isinstance(n.value, python_ast.Str):
                self.generic_visit(n.value)
                n.value.ast_type = "DocStr"
                del node.body[0]
                node.doc_string = n.value

        return node

    def visit_Module(self, node):
        node.path = self._module_path
        node.resolved_path = self._resolved_path
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
            node = node.value
            node.ast_type = self._modification_offsets[(node.lineno, node.col_offset)]

        return node

    def visit_Subscript(self, node):
        """
        Maintain consistency of `Subscript.slice` across python versions.

        Starting from python 3.9, the `Index` node type has been deprecated,
        and made impossible to instantiate via regular means. Here we do awful
        hacky black magic to create an `Index` node. We need our own parser.
        """
        self.generic_visit(node)

        if not isinstance(node.slice, python_ast.Index):
            index = python_ast.Constant(value=node.slice, ast_type="Index")
            index.__class__ = python_ast.Index
            self.generic_visit(index)
            node.slice = index

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
            node.n = value

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

        elif isinstance(node.n, float):
            node.ast_type = "Decimal"
            node.n = Decimal(value)

        elif isinstance(node.n, int):
            node.ast_type = "Int"

        else:
            raise CompilerPanic(f"Unexpected type for Constant value: {type(node.n).__name__}")

        return node

    def visit_UnaryOp(self, node):
        """
        Adjust operand value and discard unary operations, where possible.

        This is done so that negative decimal literals are accurately represented.
        """
        self.generic_visit(node)

        is_sub = isinstance(node.op, python_ast.USub)
        is_num = (
            hasattr(node.operand, "n")
            and not isinstance(node.operand.n, bool)
            and isinstance(node.operand.n, (int, Decimal))
        )
        if is_sub and is_num:
            node.operand.n = 0 - node.operand.n
            node.operand.col_offset = node.col_offset
            node.operand.node_source_code = node.node_source_code
            return node.operand
        else:
            return node


def annotate_python_ast(
    parsed_ast: python_ast.AST,
    source_code: str,
    modification_offsets: Optional[ModificationOffsets] = None,
    loop_var_annotations: Optional[dict[int, python_ast.AST]] = None,
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
    source_code : str
        The originating source code of the AST.
    modification_offsets : dict, optional
        A mapping of class names to their original class types.

    Returns
    -------
        The annotated and optimized AST.
    """

    tokens = asttokens.ASTTokens(source_code, tree=cast(Optional[python_ast.Module], parsed_ast))
    visitor = AnnotatingVisitor(
        source_code,
        modification_offsets,
        tokens,
        source_id,
        module_path=module_path,
        resolved_path=resolved_path,
    )
    visitor.visit(parsed_ast)

    for _, v in loop_var_annotations.items():
        tokens = asttokens.ASTTokens(
            v["source_code"], tree=cast(Optional[python_ast.Module], v["parsed_ast"])
        )
        visitor = AnnotatingVisitor(
            v["source_code"],
            {},
            tokens,
            source_id,
            module_path=module_path,
            resolved_path=resolved_path,
        )
        visitor.visit(v["parsed_ast"])

    return parsed_ast

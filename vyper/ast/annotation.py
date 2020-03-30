import ast as python_ast
from decimal import (
    Decimal,
)
from typing import (
    Optional,
)

import asttokens

from vyper.exceptions import (
    CompilerPanic,
    SyntaxException,
)
from vyper.typing import (
    ClassTypes,
)


class AnnotatingVisitor(python_ast.NodeTransformer):
    _source_code: str
    _class_types: ClassTypes

    def __init__(
        self,
        source_code: str,
        class_types: Optional[ClassTypes] = None,
        source_id: int = 0,
    ):
        self._source_id = source_id
        self._source_code: str = source_code
        self.counter: int = 0
        if class_types is not None:
            self._class_types = class_types
        else:
            self._class_types = {}

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
        end = node.last_token.end if hasattr(node, "last_token") else (None, None)

        node.lineno = start[0]
        node.col_offset = start[1]
        node.end_lineno = end[0]
        node.end_col_offset = end[1]

        if hasattr(node, "last_token"):
            start_pos = node.first_token.startpos
            end_pos = node.last_token.endpos
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
        return self._visit_docstring(node)

    def visit_FunctionDef(self, node):
        return self._visit_docstring(node)

    def visit_ClassDef(self, node):
        """
        Annotate the Class node with it's original type from the Vyper source.

        Vyper uses `struct` and `contract` in place of `class`, however these
        values must be substituted out to create parseable Python. The Python
        node is annotated with the original value via the `class_type` member.
        """
        self.generic_visit(node)

        node.class_type = self._class_types.get(node.name)
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
        else:
            raise SyntaxException(
                f"Invalid syntax (unsupported Python Constant AST node).",
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
        modifies `ast_type` to seperate `Num` into more granular Vyper node
        classes.
        """
        # modify vyper AST type according to the format of the literal value
        self.generic_visit(node)
        value = node.node_source_code

        # deduce non base-10 types based on prefix
        literal_prefixes = {'0x': "Hex", '0b': "Binary", '0o': "Octal"}
        if value.lower()[:2] in literal_prefixes:
            node.ast_type = literal_prefixes[value.lower()[:2]]
            node.n = value
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

        # TODO once grammar is updated, remove this
        # UAdd has no effect on the value of it's operand, so it is discarded
        if isinstance(node.op, python_ast.UAdd):
            return node.operand

        is_sub = isinstance(node.op, python_ast.USub)
        is_num = (
            hasattr(node.operand, 'n') and
            not isinstance(node.operand.n, bool) and
            isinstance(node.operand.n, (int, Decimal))
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
    class_types: Optional[ClassTypes] = None,
    source_id: int = 0,
) -> python_ast.AST:
    """
    Annotate and optimize a Python AST in preparation conversion to a Vyper AST.

    Parameters
    ----------
    parsed_ast : AST
        The AST to be annotated and optimized.
    source_code : str
        The originating source code of the AST.
    class_types : dict, optional
        A mapping of class names to their original class types.

    Returns
    -------
        The annotated and optimized AST.
    """

    asttokens.ASTTokens(source_code, tree=parsed_ast)
    AnnotatingVisitor(source_code, class_types, source_id).visit(parsed_ast)

    return parsed_ast

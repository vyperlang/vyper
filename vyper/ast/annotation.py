import ast as python_ast
import tokenize
from decimal import Decimal
from typing import Optional

import asttokens

from vyper.exceptions import CompilerPanic, SyntaxException
from vyper.typing import ModificationOffsets


class AnnotatingVisitor(python_ast.NodeTransformer):
    _source_code: str
    _modification_offsets: ModificationOffsets

    def __init__(
        self,
        source_code: str,
        modification_offsets: Optional[ModificationOffsets],
        tokens: asttokens.ASTTokens,
        source_id: int,
        contract_name: Optional[str],
    ):
        self._tokens = tokens
        self._source_id = source_id
        self._contract_name = contract_name
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
        node.name = self._contract_name
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
        modifies `ast_type` to seperate `Num` into more granular Vyper node
        classes.
        """
        # modify vyper AST type according to the format of the literal value
        self.generic_visit(node)
        value = node.node_source_code

        # deduce non base-10 types based on prefix
        literal_prefixes = {"0x": "Hex", "0o": "Octal"}
        if value.lower()[:2] in literal_prefixes:
            node.ast_type = literal_prefixes[value.lower()[:2]]
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

        # TODO once grammar is updated, remove this
        # UAdd has no effect on the value of it's operand, so it is discarded
        if isinstance(node.op, python_ast.UAdd):
            return node.operand

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
    source_id: int = 0,
    contract_name: Optional[str] = None,
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

    tokens = asttokens.ASTTokens(source_code, tree=parsed_ast)
    visitor = AnnotatingVisitor(source_code, modification_offsets, tokens, source_id, contract_name)
    visitor.visit(parsed_ast)

    return parsed_ast

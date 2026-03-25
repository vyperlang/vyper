import bisect
import re
from typing import Dict, List, Tuple, Union

from vyper.ast import nodes as vy_ast
from vyper.exceptions import CompilerPanic


class LineNumbers:
    """
    Class to convert between character offsets in a text string, and pairs (line, column) of 1-based
    line and 0-based column numbers.

    Vendored from asttokens.
    """

    def __init__(self, text: str) -> None:
        # a list of character offsets of each line's first character
        self._line_offsets = [m.start(0) for m in re.finditer(r"^", text, re.M)]
        self._text_len = len(text)

    def offset_to_line(self, offset: int) -> Tuple[int, int]:
        """
        Converts 0-based character offset to pair (line, col) of 1-based line and 0-based column
        numbers.
        """
        offset = max(0, min(self._text_len, offset))
        line_index = bisect.bisect_right(self._line_offsets, offset) - 1
        return (line_index + 1, offset - self._line_offsets[line_index])


def ast_to_dict(ast_struct: Union[vy_ast.VyperNode, List]) -> Union[Dict, List]:
    """
    Converts a Vyper AST node, or list of nodes, into a dictionary suitable for
    output to the user.
    """
    if isinstance(ast_struct, vy_ast.VyperNode):
        return ast_struct.to_dict()
    elif isinstance(ast_struct, list):
        return [i.to_dict() for i in ast_struct]
    else:
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

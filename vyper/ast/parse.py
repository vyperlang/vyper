import ast as python_ast
import copy
import pickle
import tokenize
from decimal import Decimal
from functools import cached_property
from typing import Optional

from vyper.ast import nodes as vy_ast
from vyper.ast.pre_parser import PreParser
from vyper.exceptions import CompilerPanic, ParserException, SyntaxException
from vyper.utils import sha256sum
from vyper.warnings import Deprecation, vyper_warn

PYTHON_AST_SINGLETONS = (
    python_ast.cmpop,
    python_ast.operator,
    python_ast.unaryop,
    python_ast.boolop,
    python_ast.expr_context,
)


def parse_to_ast(
    vyper_source: str,
    source_id: int = 0,
    module_path: Optional[str] = None,
    resolved_path: Optional[str] = None,
    is_interface: bool = False,
) -> vy_ast.Module:
    try:
        return _parse_to_ast(vyper_source, source_id, module_path, resolved_path, is_interface)
    except SyntaxException as e:
        e.resolved_path = resolved_path
        raise e


def _parse_to_ast(
    vyper_source: str,
    source_id: int = 0,
    module_path: Optional[str] = None,
    resolved_path: Optional[str] = None,
    is_interface: bool = False,
) -> vy_ast.Module:
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
    source_id: int, optional
        The source ID generated for this source code.
        Corresponds to FileInput.source_id
    module_path: str, optional
        The path of the source code
        Corresponds to FileInput.path
    resolved_path: str, optional
        The resolved path of the source code
        Corresponds to FileInput.resolved_path
    is_interface: bool
        Indicates whether the source code should
        be parsed as an interface file.

    Returns
    -------
    list
        Untyped, unoptimized Vyper AST nodes.
    """
    if "\x00" in vyper_source:
        raise ParserException("No null bytes (\\x00) allowed in the source code.")
    pre_parser = PreParser(is_interface)
    pre_parser.parse(vyper_source)

    try:
        py_ast = python_ast.parse(pre_parser.reformatted_code)
    except SyntaxError as e:
        offset = e.offset
        if offset is not None:
            # SyntaxError offset is 1-based, not 0-based (see:
            # https://docs.python.org/3/library/exceptions.html#SyntaxError.offset)
            offset -= 1

            # adjust the column of the error if it was modified by the pre-parser
            if e.lineno is not None:  # help mypy
                offset += pre_parser.adjustments.get((e.lineno, offset), 0)

        new_e = SyntaxException(str(e), vyper_source, e.lineno, offset)

        likely_errors = ("staticall", "staticcal")
        tmp = str(new_e)
        for s in likely_errors:
            if s in tmp:
                new_e._hint = "did you mean `staticcall`?"
                break

        raise new_e from None

    annotate_python_ast(
        py_ast,
        vyper_source,
        pre_parser,
        source_id=source_id,
        module_path=module_path,
        resolved_path=resolved_path,
    )

    # postcondition: consumed all the for loop annotations
    assert len(pre_parser.for_loop_annotations) == 0

    # postcondition: we have used all the hex strings found by the
    # pre-parser
    assert len(pre_parser.hex_string_locations) == 0

    # Convert to Vyper AST.
    module = vy_ast.get_node(py_ast)
    assert isinstance(module, vy_ast.Module)  # mypy hint
    module.is_interface = is_interface

    module.settings = pre_parser.settings

    return module


LINE_INFO_FIELDS = ("lineno", "col_offset", "end_lineno", "end_col_offset")


def annotate_python_ast(
    parsed_ast: python_ast.Module,
    vyper_source: str,
    pre_parser: PreParser,
    source_id: int = 0,
    module_path: Optional[str] = None,
    resolved_path: Optional[str] = None,
) -> python_ast.AST:
    """
    Annotate and optimize a Python AST in preparation for conversion to a Vyper AST.

    Parameters
    ----------
    parsed_ast : AST
        The AST to be annotated and optimized.
    vyper_source: str
        The original vyper source code
    pre_parser: PreParser
        PreParser object.

    Returns
    -------
        The annotated and optimized AST.
    """
    visitor = AnnotatingVisitor(
        vyper_source, pre_parser, source_id, module_path=module_path, resolved_path=resolved_path
    )
    visitor.visit(parsed_ast)

    return parsed_ast


def _deepcopy_ast(ast_node: python_ast.AST):
    # pickle roundtrip is faster than copy.deepcopy() here.
    return pickle.loads(pickle.dumps(ast_node))


class AnnotatingVisitor(python_ast.NodeTransformer):
    _source_code: str
    _pre_parser: PreParser
    _parents: list[python_ast.AST]

    def __init__(
        self,
        source_code: str,
        pre_parser: PreParser,
        source_id: int,
        module_path: Optional[str] = None,
        resolved_path: Optional[str] = None,
    ):
        self._source_id = source_id
        self._module_path = module_path
        self._resolved_path = resolved_path
        self._source_code = source_code
        self._pre_parser = pre_parser
        self._parents = []

        self.counter: int = 0

    @cached_property
    def source_lines(self):
        return self._source_code.splitlines(keepends=True)

    @cached_property
    def line_offsets(self):
        ofst = 0
        # ensure line_offsets has at least 1 entry for 0-line source
        ret = {1: ofst}
        for lineno, line in enumerate(self.source_lines):
            ret[lineno + 1] = ofst
            ofst += len(line)
        return ret

    def generic_visit(self, node):
        """
        Adds location info to all python ast nodes and replaces python ast nodes
        that are singletons with a copy so that the location info will be unique,
        before annotating the nodes with information that simplifies Vyper node
        generation.
        """
        if isinstance(node, PYTHON_AST_SINGLETONS):
            # for performance reasons, these AST nodes are represented as
            # singletons in the C parser. however, since we want to add
            # different source annotations for each operator, we create
            # a copy here.
            node = copy.copy(node)

        # adapted from cpython Lib/ast.py. adds line/col info to ast,
        # but unlike Lib/ast.py, adjusts *all* ast nodes, not just the
        # one that python defines to have line/col info.
        # https://github.com/python/cpython/blob/62729d79206014886f5d/Lib/ast.py#L228
        for field in LINE_INFO_FIELDS:
            if len(self._parents) > 0:
                parent = self._parents[-1]
                val = getattr(node, field, None)
                if val is None:
                    # try to get the field from the parent
                    val = getattr(parent, field)
                setattr(node, field, val)
            else:
                assert hasattr(node, field), node

        # decorate every node with the original source code to allow
        # pretty-printing errors
        node.full_source_code = self._source_code
        node.node_id = self.counter
        self.counter += 1
        node.ast_type = node.__class__.__name__

        adjustments = self._pre_parser.adjustments

        adj = adjustments.get((node.lineno, node.col_offset), 0)
        node.col_offset += adj

        adj = adjustments.get((node.end_lineno, node.end_col_offset), 0)
        node.end_col_offset += adj

        start_pos = self.line_offsets[node.lineno] + node.col_offset
        end_pos = self.line_offsets[node.end_lineno] + node.end_col_offset

        node.src = f"{start_pos}:{end_pos-start_pos}:{self._source_id}"
        node.node_source_code = self._source_code[start_pos:end_pos]

        # keep track of the current path thru the AST
        self._parents.append(node)
        try:
            node = super().generic_visit(node)
        finally:
            self._parents.pop()

        return node

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
        node.lineno = 1
        node.col_offset = 0
        node.end_lineno = max(1, len(self.source_lines))

        if len(self.source_lines) > 0:
            node.end_col_offset = len(self.source_lines[-1])
        else:
            node.end_col_offset = 0

        # TODO: is this the best place for these? maybe they can be on
        # CompilerData instead.
        node.path = self._module_path
        node.resolved_path = self._resolved_path
        node.source_sha256sum = sha256sum(self._source_code)
        node.source_id = self._source_id
        return self._visit_docstring(node)

    def visit_FunctionDef(self, node):
        return self._visit_docstring(node)

    def visit_ClassDef(self, node):
        """
        Convert the `ClassDef` node into a Vyper-specific node type.

        Vyper uses `struct` and `interface` in place of `class`, however these
        values must be substituted out to create parseable Python. The Python
        node is annotated with the desired Vyper type via the `ast_type` member.
        """
        self.generic_visit(node)

        node.ast_type = self._pre_parser.keyword_translations[(node.lineno, node.col_offset)]
        return node

    def visit_For(self, node):
        """
        Visit a For node, splicing in the loop variable annotation provided by
        the pre-parser
        """
        key = (node.lineno, node.col_offset)
        annotation_tokens = self._pre_parser.for_loop_annotations.pop(key)

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
            # do we need to fix location info here?
            fake_node = _deepcopy_ast(fake_node)
        except SyntaxError as e:
            raise SyntaxException(
                "invalid type annotation", self._source_code, node.lineno, node.col_offset
            ) from e
        # block things like `for x: uint256 = 5 in ...`
        if (value_node := fake_node.value) is not None:
            raise SyntaxException(
                "invalid type annotation",
                self._source_code,
                value_node.lineno,
                value_node.col_offset,
            )

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
            key = (node.lineno, node.col_offset)
            node.ast_type = self._pre_parser.keyword_translations[key]

        return node

    def visit_Await(self, node):
        start_pos = node.lineno, node.col_offset
        self.generic_visit(node)
        node.ast_type = self._pre_parser.keyword_translations[start_pos]
        return node

    def visit_Call(self, node):
        # Convert structs declared as `Dict` node for vyper < 0.4.0 to kwargs
        if len(node.args) == 1 and isinstance(node.args[0], python_ast.Dict):
            msg = "Instantiating a struct using a dictionary is deprecated "
            msg += "as of v0.4.0 and will be disallowed in a future release. "
            msg += "Use kwargs instead e.g. Foo(a=1, b=2)"

            # add full_source_code so that str(VyperException(msg, node)) works
            node.full_source_code = self._source_code
            vyper_warn(Deprecation(msg, node))

            dict_ = node.args[0]
            kw_list = []

            assert len(dict_.keys) == len(dict_.values)
            for key, value in zip(dict_.keys, dict_.values):
                replacement_kw_node = python_ast.keyword(key.id, value)
                # set locations
                for attr in LINE_INFO_FIELDS:
                    setattr(replacement_kw_node, attr, getattr(key, attr))
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
            key = (node.lineno, node.col_offset)
            if key in self._pre_parser.hex_string_locations:
                if len(node.value) % 2 != 0:
                    raise SyntaxException(
                        "Hex string must have an even number of characters",
                        self._source_code,
                        node.lineno,
                        node.col_offset,
                    )
                node.ast_type = "HexBytes"
                self._pre_parser.hex_string_locations.remove(key)
            else:
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

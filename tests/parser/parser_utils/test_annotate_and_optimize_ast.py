import ast as python_ast

from vyper.parser.parser_utils import (
    annotate_ast,
)
from vyper.parser.pre_parser import (
    pre_parse,
)


class AssertionVisitor(python_ast.NodeVisitor):
    def assert_about_node(self, node):
        assert False

    def generic_visit(self, node):
        self.assert_about_node(node)

        super().generic_visit(node)


TEST_CONTRACT_SOURCE_CODE = """
struct S:
    a: bool
    b: int128

contract ERC20Contract:
    def name() -> string[64]: constant

@public
def foo() -> int128:
    return -(-(-1))
"""


def get_contract_info(source_code):
    class_types, reformatted_code = pre_parse(source_code)
    py_ast = python_ast.parse(reformatted_code)

    annotate_ast(py_ast, reformatted_code, class_types)

    return py_ast, reformatted_code


def test_it_annotates_ast_with_source_code():
    contract_ast, reformatted_code = get_contract_info(TEST_CONTRACT_SOURCE_CODE)

    class AssertSourceCodePresent(AssertionVisitor):
        def assert_about_node(self, node):
            assert node.source_code is reformatted_code

    AssertSourceCodePresent().visit(contract_ast)


def test_it_annotates_ast_with_class_types():
    contract_ast, _ = get_contract_info(TEST_CONTRACT_SOURCE_CODE)

    struct_def = contract_ast.body[0]
    contract_def = contract_ast.body[1]

    assert struct_def.class_type == 'struct'
    assert contract_def.class_type == 'contract'


def test_it_rewrites_unary_subtractions():
    contract_ast, _ = get_contract_info(TEST_CONTRACT_SOURCE_CODE)

    function_def = contract_ast.body[2]
    return_stmt = function_def.body[0]

    assert isinstance(return_stmt.value, python_ast.Num)
    assert return_stmt.value.n == -1

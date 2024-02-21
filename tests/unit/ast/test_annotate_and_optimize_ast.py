import ast as python_ast

from vyper.ast.parse import annotate_python_ast, pre_parse


class AssertionVisitor(python_ast.NodeVisitor):
    def assert_about_node(self, node):
        raise AssertionError()

    def generic_visit(self, node):
        self.assert_about_node(node)

        super().generic_visit(node)


TEST_CONTRACT_SOURCE_CODE = """
struct S:
    a: bool
    b: int128

interface ERC20Contract:
    def name() -> String[64]: view

@external
def foo() -> int128:
    return -(-(-1))
"""


def get_contract_info(source_code):
    _, loop_var_annotations, class_types, reformatted_code = pre_parse(source_code)
    py_ast = python_ast.parse(reformatted_code)

    annotate_python_ast(py_ast, reformatted_code, loop_var_annotations, class_types)

    return py_ast, reformatted_code


def test_it_annotates_ast_with_source_code():
    contract_ast, reformatted_code = get_contract_info(TEST_CONTRACT_SOURCE_CODE)

    class AssertSourceCodePresent(AssertionVisitor):
        def assert_about_node(self, node):
            assert node.full_source_code is reformatted_code

    AssertSourceCodePresent().visit(contract_ast)


def test_it_annotates_ast_with_class_types():
    contract_ast, _ = get_contract_info(TEST_CONTRACT_SOURCE_CODE)

    struct_def = contract_ast.body[0]
    contract_def = contract_ast.body[1]

    assert struct_def.ast_type == "StructDef"
    assert contract_def.ast_type == "InterfaceDef"


def test_it_rewrites_unary_subtractions():
    contract_ast, _ = get_contract_info(TEST_CONTRACT_SOURCE_CODE)

    function_def = contract_ast.body[2]
    return_stmt = function_def.body[0]

    assert isinstance(return_stmt.value, python_ast.Num)
    assert return_stmt.value.n == -1

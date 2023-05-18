import json

from vyper import compiler
from vyper.ast.utils import ast_to_dict, dict_to_ast, parse_to_ast


def get_node_ids(ast_struct, ids=None):
    if ids is None:
        ids = []

    for k, v in ast_struct.items():
        if isinstance(v, dict):
            ids = get_node_ids(v, ids)
        elif isinstance(v, list):
            for x in v:
                ids = get_node_ids(x, ids)
        elif k == "node_id":
            ids.append(v)
        elif v is None or isinstance(v, (str, int)):
            continue
        else:
            raise Exception("Unknown ast_struct provided.")
    return ids


def test_ast_to_dict_node_id():
    code = """
@external
def test() -> int128:
    a: uint256 = 100
    return 123
    """
    dict_out = compiler.compile_code(code, ["ast_dict"])
    node_ids = get_node_ids(dict_out)

    assert len(node_ids) == len(set(node_ids))


def test_basic_ast():
    code = """
a: int128
    """
    dict_out = compiler.compile_code(code, ["ast_dict"])
    assert dict_out["ast_dict"]["ast"]["body"][0] == {
        "annotation": {
            "ast_type": "Name",
            "col_offset": 3,
            "end_col_offset": 9,
            "end_lineno": 2,
            "id": "int128",
            "lineno": 2,
            "node_id": 4,
            "src": "4:6:0",
        },
        "ast_type": "VariableDecl",
        "col_offset": 0,
        "end_col_offset": 9,
        "end_lineno": 2,
        "lineno": 2,
        "node_id": 1,
        "src": "1:9:0",
        "target": {
            "ast_type": "Name",
            "col_offset": 0,
            "end_col_offset": 1,
            "end_lineno": 2,
            "id": "a",
            "lineno": 2,
            "node_id": 2,
            "src": "1:1:0",
        },
        "value": None,
        "is_constant": False,
        "is_immutable": False,
        "is_public": False,
        "is_transient": False,
    }


def test_implements_ast():
    code = """
interface Foo:
    def foo() -> uint256: view

implements: Foo

@external
@view
def foo() -> uint256:
    return 1
    """
    dict_out = compiler.compile_code(code, ["ast_dict"])
    assert dict_out["ast_dict"]["ast"]["body"][1] == {
        "col_offset": 0,
        "annotation": {
            "col_offset": 12,
            "end_col_offset": 15,
            "node_id": 12,
            "src": "60:3:0",
            "ast_type": "Name",
            "end_lineno": 5,
            "lineno": 5,
            "id": "Foo",
        },
        "end_col_offset": 15,
        "node_id": 9,
        "src": "48:15:0",
        "ast_type": "ImplementsDecl",
        "target": {
            "col_offset": 0,
            "end_col_offset": 10,
            "node_id": 10,
            "src": "48:10:0",
            "ast_type": "Name",
            "end_lineno": 5,
            "lineno": 5,
            "id": "implements",
        },
        "end_lineno": 5,
        "lineno": 5,
    }


def test_dict_to_ast():
    code = """
@external
def test() -> int128:
    a: uint256 = 100
    b: int128 = -22
    c: decimal = -3.3133700
    d: Bytes[11] = b"oh hai mark"
    e: Bytes[1] = 0b01010101
    f: Bytes[88] = b"\x01\x70"
    g: String[100] = "  baka baka   "
    h: address = 0xdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef
    i: bool = False
    return 123
    """

    original_ast = parse_to_ast(code)
    out_dict = ast_to_dict(original_ast)
    out_json = json.dumps(out_dict)
    new_dict = json.loads(out_json)
    new_ast = dict_to_ast(new_dict)

    assert new_ast == original_ast

import json

from vyper import compiler
from vyper.ast.nodes import NODE_SRC_ATTRIBUTES
from vyper.ast.parse import parse_to_ast
from vyper.ast.utils import ast_to_dict, dict_to_ast


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
            raise Exception(f"Unknown ast_struct provided. {k}, {v}")
    return ids


def test_ast_to_dict_node_id():
    code = """
@external
def test() -> int128:
    a: uint256 = 100
    return 123
    """
    dict_out = compiler.compile_code(code, output_formats=["ast_dict"])
    node_ids = get_node_ids(dict_out)

    assert len(node_ids) == len(set(node_ids))


def test_basic_ast():
    code = """
a: int128
    """
    dict_out = compiler.compile_code(code, output_formats=["annotated_ast_dict"], source_id=0)
    assert dict_out["annotated_ast_dict"]["ast"]["body"][0] == {
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
            "type": "int128",
        },
        "value": None,
        "is_constant": False,
        "is_immutable": False,
        "is_public": False,
        "is_transient": False,
        "type": "int128",
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
    dict_out = compiler.compile_code(code, output_formats=["ast_dict"], source_id=0)
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


# strip source annotations like lineno, we don't care for inspecting
# the analysis result
def _strip_source_annotations(dict_node):
    to_strip = NODE_SRC_ATTRIBUTES + ("node_id",)
    if isinstance(dict_node, dict):
        for k in list(dict_node.keys()):
            if k in to_strip:
                del dict_node[k]
                continue
            _strip_source_annotations(dict_node[k])
    elif isinstance(dict_node, list):
        for child in dict_node:
            _strip_source_annotations(child)


def test_output_variable_read_write_analysis(make_input_bundle, chdir_tmp_path):
    # test we output the result of variable read/write correctly
    lib1 = """
struct Foo:
    a: uint256
    b: String[3]
    c: decimal

struct Bar:
    items: Foo[2]

counter: uint256

bars: DynArray[Bar, 10]
    """
    code = """
import lib1

initializes: lib1

counter: uint256

@internal
def foo():
    x: uint256 = lib1.counter
    lib1.counter += 1

@internal
def bar():
    x: uint256 = lib1.counter
    y: uint256 = self.counter
    lib1.counter += 1

@internal
def baz():
    self.bar()  # reads both lib1.counter and self.counter
    self.counter += 1

@internal
def qux():
    lib1.bars = []
    lib1.bars[0] = empty(lib1.Bar)
    lib1.bars[1].items = empty(lib1.Foo[2])

    lib1.bars[1].items[0].a = 1
    lib1.bars[0].items[1].c = 10.0

@internal
def qux2():
    self.qux()
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1})

    out = compiler.compile_code(
        code,
        contract_path="main.vy",
        input_bundle=input_bundle,
        output_formats=["annotated_ast_dict"],
        source_id=0,
    )["annotated_ast_dict"]["ast"]
    _strip_source_annotations(out)

    foo, bar, baz, qux, qux2 = out["body"][3:]
    assert foo["name"] == "foo"
    assert foo["body"] == [
        {
            "annotation": {"ast_type": "Name", "id": "uint256"},
            "ast_type": "AnnAssign",
            "target": {"ast_type": "Name", "id": "x", "type": "uint256"},
            "value": {
                "ast_type": "Attribute",
                "attr": "counter",
                "type": "uint256",
                "value": {
                    "ast_type": "Name",
                    "id": "lib1",
                    "type": "lib1.vy",
                    "type_decl_node": {"source_id": 0},
                },
                "variable_reads": [{"access_path": [], "module": "lib1.vy", "variable": "counter"}],
            },
        },
        {
            "ast_type": "AugAssign",
            "op": {"ast_type": "Add"},
            "target": {
                "ast_type": "Attribute",
                "attr": "counter",
                "type": "uint256",
                "value": {
                    "ast_type": "Name",
                    "id": "lib1",
                    "type": "lib1.vy",
                    "type_decl_node": {"source_id": 0},
                },
                "variable_reads": [{"access_path": [], "module": "lib1.vy", "variable": "counter"}],
                "variable_writes": [
                    {"access_path": [], "module": "lib1.vy", "variable": "counter"}
                ],
            },
            "value": {"ast_type": "Int", "type": "uint256", "value": 1},
        },
    ]

    assert bar["name"] == "bar"
    assert bar["body"] == [
        {
            "annotation": {"ast_type": "Name", "id": "uint256"},
            "ast_type": "AnnAssign",
            "target": {"ast_type": "Name", "id": "x", "type": "uint256"},
            "value": {
                "ast_type": "Attribute",
                "attr": "counter",
                "type": "uint256",
                "value": {
                    "ast_type": "Name",
                    "id": "lib1",
                    "type": "lib1.vy",
                    "type_decl_node": {"source_id": 0},
                },
                "variable_reads": [{"access_path": [], "module": "lib1.vy", "variable": "counter"}],
            },
        },
        {
            "annotation": {"ast_type": "Name", "id": "uint256"},
            "ast_type": "AnnAssign",
            "target": {"ast_type": "Name", "id": "y", "type": "uint256"},
            "value": {
                "ast_type": "Attribute",
                "attr": "counter",
                "type": "uint256",
                "value": {"ast_type": "Name", "id": "self", "type": "self"},
                "variable_reads": [{"access_path": [], "module": "main.vy", "variable": "counter"}],
            },
        },
        {
            "ast_type": "AugAssign",
            "op": {"ast_type": "Add"},
            "target": {
                "ast_type": "Attribute",
                "attr": "counter",
                "type": "uint256",
                "value": {
                    "ast_type": "Name",
                    "id": "lib1",
                    "type": "lib1.vy",
                    "type_decl_node": {"source_id": 0},
                },
                "variable_reads": [{"access_path": [], "module": "lib1.vy", "variable": "counter"}],
                "variable_writes": [
                    {"access_path": [], "module": "lib1.vy", "variable": "counter"}
                ],
            },
            "value": {"ast_type": "Int", "type": "uint256", "value": 1},
        },
    ]

    assert baz["name"] == "baz"
    assert baz["body"] == [
        {
            "ast_type": "Expr",
            "value": {
                "args": [],
                "ast_type": "Call",
                "func": {
                    "ast_type": "Attribute",
                    "attr": "bar",
                    "type": "def bar():",
                    "type_decl_node": {"source_id": 0},
                    "value": {"ast_type": "Name", "id": "self", "type": "self"},
                    "variable_reads": [
                        {"access_path": [], "module": "lib1.vy", "variable": "counter"},
                        {"access_path": [], "module": "main.vy", "variable": "counter"},
                    ],
                    "variable_writes": [
                        {"access_path": [], "module": "lib1.vy", "variable": "counter"}
                    ],
                },
                "keywords": [],
                "type": "(void)",
            },
        },
        {
            "ast_type": "AugAssign",
            "op": {"ast_type": "Add"},
            "target": {
                "ast_type": "Attribute",
                "attr": "counter",
                "type": "uint256",
                "value": {"ast_type": "Name", "id": "self", "type": "self"},
                "variable_reads": [{"access_path": [], "module": "main.vy", "variable": "counter"}],
                "variable_writes": [
                    {"access_path": [], "module": "main.vy", "variable": "counter"}
                ],
            },
            "value": {"ast_type": "Int", "type": "uint256", "value": 1},
        },
    ]

    assert qux["name"] == "qux"
    assert qux["body"] == []

    assert qux2["name"] == "qux2"
    assert qux2["body"] == []

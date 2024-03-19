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
        "is_constant": False,
        "is_immutable": False,
        "is_public": False,
        "is_transient": False,
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
            "type": {"bits": 128, "is_signed": True, "name": "int128", "typeclass": "integer"},
        },
        "type": {"bits": 128, "is_signed": True, "name": "int128", "typeclass": "integer"},
        "value": None,
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
def _strip_source_annotations(dict_node, to_strip):
    if isinstance(dict_node, dict):
        for k in list(dict_node.keys()):
            if k in to_strip:
                del dict_node[k]
                continue
            if "decl_node" not in k:
                _strip_source_annotations(dict_node[k], to_strip)
    elif isinstance(dict_node, list):
        for child in dict_node:
            _strip_source_annotations(child, to_strip)


def test_output_type_info(make_input_bundle, chdir_tmp_path):
    # test type info is output in the ast dict
    # test different, complex types, and test import info is also output
    lib1 = """
struct Foo:
    x: uint256

event Bar:
    pass

struct Baz:
    x: decimal
    y: Bytes[20]
    z: String[32]
    w: uint256
    u: address

interface Qux:
    def return_tuple() -> (Foo[1], uint256): nonpayable

foo_var: Foo
sarray_var: Foo[1]
darray_var: DynArray[Foo, 5]
interface_var: Qux

hashmap_var: HashMap[address, Foo]

sarray_var2: uint256[2]
darray_var2: DynArray[uint256, 5]

@internal
def foo():
    t: uint256 = max_value(uint256)
    u: int24 = empty(int24)

    self.foo_var = empty(Foo)
    self.sarray_var[0] = empty(Foo)
    self.darray_var[1] = empty(Foo)

    self.sarray_var, t = extcall self.interface_var.return_tuple()

@external
def bar():
    s: bytes24 = empty(bytes24)
    """

    main = """
import lib1

initializes: lib1

@internal
def foo():
    lib1.foo()
    log lib1.Bar()
    s: lib1.Foo = empty(lib1.Foo)
    """

    input_bundle = make_input_bundle({"lib1.vy": lib1, "main.vy": main})

    lib1_file = input_bundle.load_file("lib1.vy")
    out = compiler.compile_from_file_input(
        lib1_file, input_bundle=input_bundle, output_formats=["annotated_ast_dict"]
    )
    lib1_ast = out["annotated_ast_dict"]["ast"]
    lib1_sha256sum = lib1_ast.pop("source_sha256sum")
    assert lib1_sha256sum == lib1_file.sha256sum
    to_strip = NODE_SRC_ATTRIBUTES + ("resolved_path", "variable_reads", "variable_writes")
    _strip_source_annotations(lib1_ast, to_strip=to_strip)

    main_file = input_bundle.load_file("main.vy")
    out = compiler.compile_from_file_input(
        main_file, input_bundle=input_bundle, output_formats=["annotated_ast_dict"]
    )
    main_ast = out["annotated_ast_dict"]["ast"]
    main_sha256sum = main_ast.pop("source_sha256sum")
    assert main_sha256sum == main_file.sha256sum
    _strip_source_annotations(main_ast, to_strip=to_strip)

    # TODO: would be nice to refactor this into bunch of small test cases
    assert main_ast == {
        "ast_type": "Module",
        "body": [
            {
                "alias": None,
                "ast_type": "Import",
                "import_info": {
                    "alias": "lib1",
                    "file_sha256sum": lib1_file.sha256sum,
                    "path": "lib1.vy",
                    "qualified_module_name": "lib1",
                    "source_id": 0,
                },
                "name": "lib1",
                "node_id": 1,
            },
            {
                "annotation": {"ast_type": "Name", "id": "lib1", "node_id": 6},
                "ast_type": "InitializesDecl",
                "node_id": 3,
            },
            {
                "args": {
                    "args": [],
                    "ast_type": "arguments",
                    "default": None,
                    "defaults": [],
                    "node_id": 9,
                },
                "ast_type": "FunctionDef",
                "body": [
                    {
                        "ast_type": "Expr",
                        "node_id": 10,
                        "value": {
                            "args": [],
                            "ast_type": "Call",
                            "func": {
                                "ast_type": "Attribute",
                                "attr": "foo",
                                "node_id": 12,
                                "type": {
                                    "name": "foo",
                                    "type_decl_node": {"node_id": 119, "source_id": 0},
                                    "typeclass": "contract_function",
                                },
                                "value": {
                                    "ast_type": "Name",
                                    "id": "lib1",
                                    "node_id": 13,
                                    "type": {
                                        "name": "lib1.vy",
                                        "type_decl_node": {"node_id": 0, "source_id": 0},
                                        "typeclass": "module",
                                    },
                                },
                            },
                            "keywords": [],
                            "node_id": 11,
                            "type": {"name": "(void)"},
                        },
                    },
                    {
                        "ast_type": "Log",
                        "node_id": 17,
                        "type": {
                            "name": "Bar",
                            "type_decl_node": {"node_id": 7, "source_id": 0},
                            "typeclass": "event",
                        },
                        "value": {
                            "args": [],
                            "ast_type": "Call",
                            "func": {
                                "ast_type": "Attribute",
                                "attr": "Bar",
                                "node_id": 19,
                                "type": {
                                    "type_t": {
                                        "name": "Bar",
                                        "type_decl_node": {"node_id": 7, "source_id": 0},
                                        "typeclass": "event",
                                    }
                                },
                                "value": {
                                    "ast_type": "Name",
                                    "id": "lib1",
                                    "node_id": 20,
                                    "type": {
                                        "name": "lib1.vy",
                                        "type_decl_node": {"node_id": 0, "source_id": 0},
                                        "typeclass": "module",
                                    },
                                },
                            },
                            "keywords": [],
                            "node_id": 18,
                            "type": {"name": "(void)"},
                        },
                    },
                    {
                        "annotation": {
                            "ast_type": "Attribute",
                            "attr": "Foo",
                            "node_id": 26,
                            "value": {"ast_type": "Name", "id": "lib1", "node_id": 27},
                        },
                        "ast_type": "AnnAssign",
                        "node_id": 23,
                        "target": {
                            "ast_type": "Name",
                            "id": "s",
                            "node_id": 24,
                            "type": {"name": "Foo", "typeclass": "struct"},
                        },
                        "value": {
                            "args": [
                                {
                                    "ast_type": "Attribute",
                                    "attr": "Foo",
                                    "node_id": 33,
                                    "type": {"type_t": {"name": "Foo", "typeclass": "struct"}},
                                    "value": {
                                        "ast_type": "Name",
                                        "id": "lib1",
                                        "node_id": 34,
                                        "type": {
                                            "name": "lib1.vy",
                                            "type_decl_node": {"node_id": 0, "source_id": 0},
                                            "typeclass": "module",
                                        },
                                    },
                                }
                            ],
                            "ast_type": "Call",
                            "func": {
                                "ast_type": "Name",
                                "id": "empty",
                                "node_id": 31,
                                "type": {"name": "empty", "typeclass": "builtin_function"},
                            },
                            "keywords": [],
                            "node_id": 30,
                            "type": {"name": "Foo", "typeclass": "struct"},
                        },
                    },
                ],
                "decorator_list": [{"ast_type": "Name", "id": "internal", "node_id": 37}],
                "doc_string": None,
                "name": "foo",
                "node_id": 8,
                "pos": None,
                "returns": None,
            },
        ],
        "doc_string": None,
        "name": None,
        "node_id": 0,
        "path": "main.vy",
        "source_id": 1,
        "type": {
            "name": "main.vy",
            "type_decl_node": {"node_id": 0, "source_id": 1},
            "typeclass": "module",
        },
    }

    # TODO: would be nice to refactor this into bunch of small test cases
    # TODO: write the test in a way which makes the links between nodes
    # clearer
    assert lib1_ast == {
        "ast_type": "Module",
        "body": [
            {
                "ast_type": "StructDef",
                "body": [
                    {
                        "annotation": {"ast_type": "Name", "id": "uint256", "node_id": 5},
                        "ast_type": "AnnAssign",
                        "node_id": 2,
                        "target": {"ast_type": "Name", "id": "x", "node_id": 3},
                        "value": None,
                    }
                ],
                "doc_string": None,
                "name": "Foo",
                "node_id": 1,
            },
            {
                "ast_type": "EventDef",
                "body": [{"ast_type": "Pass", "node_id": 8}],
                "doc_string": None,
                "name": "Bar",
                "node_id": 7,
            },
            {
                "ast_type": "StructDef",
                "body": [
                    {
                        "annotation": {"ast_type": "Name", "id": "decimal", "node_id": 13},
                        "ast_type": "AnnAssign",
                        "node_id": 10,
                        "target": {"ast_type": "Name", "id": "x", "node_id": 11},
                        "value": None,
                    },
                    {
                        "annotation": {
                            "ast_type": "Subscript",
                            "node_id": 18,
                            "slice": {"ast_type": "Int", "node_id": 21, "value": 20},
                            "value": {"ast_type": "Name", "id": "Bytes", "node_id": 19},
                        },
                        "ast_type": "AnnAssign",
                        "node_id": 15,
                        "target": {"ast_type": "Name", "id": "y", "node_id": 16},
                        "value": None,
                    },
                    {
                        "annotation": {
                            "ast_type": "Subscript",
                            "node_id": 26,
                            "slice": {"ast_type": "Int", "node_id": 29, "value": 32},
                            "value": {"ast_type": "Name", "id": "String", "node_id": 27},
                        },
                        "ast_type": "AnnAssign",
                        "node_id": 23,
                        "target": {"ast_type": "Name", "id": "z", "node_id": 24},
                        "value": None,
                    },
                    {
                        "annotation": {"ast_type": "Name", "id": "uint256", "node_id": 34},
                        "ast_type": "AnnAssign",
                        "node_id": 31,
                        "target": {"ast_type": "Name", "id": "w", "node_id": 32},
                        "value": None,
                    },
                    {
                        "annotation": {"ast_type": "Name", "id": "address", "node_id": 39},
                        "ast_type": "AnnAssign",
                        "node_id": 36,
                        "target": {"ast_type": "Name", "id": "u", "node_id": 37},
                        "value": None,
                    },
                ],
                "doc_string": None,
                "name": "Baz",
                "node_id": 9,
            },
            {
                "ast_type": "InterfaceDef",
                "body": [
                    {
                        "args": {
                            "args": [],
                            "ast_type": "arguments",
                            "default": None,
                            "defaults": [],
                            "node_id": 43,
                        },
                        "ast_type": "FunctionDef",
                        "body": [
                            {
                                "ast_type": "Expr",
                                "node_id": 44,
                                "value": {"ast_type": "Name", "id": "nonpayable", "node_id": 45},
                            }
                        ],
                        "decorator_list": [],
                        "doc_string": None,
                        "name": "return_tuple",
                        "node_id": 42,
                        "pos": None,
                        "returns": {
                            "ast_type": "Tuple",
                            "elements": [
                                {
                                    "ast_type": "Subscript",
                                    "node_id": 48,
                                    "slice": {"ast_type": "Int", "node_id": 51, "value": 1},
                                    "value": {"ast_type": "Name", "id": "Foo", "node_id": 49},
                                },
                                {"ast_type": "Name", "id": "uint256", "node_id": 53},
                            ],
                            "node_id": 47,
                        },
                    }
                ],
                "doc_string": None,
                "name": "Qux",
                "node_id": 41,
            },
            {
                "annotation": {"ast_type": "Name", "id": "Foo", "node_id": 59},
                "ast_type": "VariableDecl",
                "is_constant": False,
                "is_immutable": False,
                "is_public": False,
                "is_transient": False,
                "node_id": 56,
                "target": {
                    "ast_type": "Name",
                    "id": "foo_var",
                    "node_id": 57,
                    "type": {"name": "Foo", "typeclass": "struct"},
                },
                "type": {"name": "Foo", "typeclass": "struct"},
                "value": None,
            },
            {
                "annotation": {
                    "ast_type": "Subscript",
                    "node_id": 64,
                    "slice": {"ast_type": "Int", "node_id": 67, "value": 1},
                    "value": {"ast_type": "Name", "id": "Foo", "node_id": 65},
                },
                "ast_type": "VariableDecl",
                "is_constant": False,
                "is_immutable": False,
                "is_public": False,
                "is_transient": False,
                "node_id": 61,
                "target": {
                    "ast_type": "Name",
                    "id": "sarray_var",
                    "node_id": 62,
                    "type": {
                        "length": 1,
                        "name": "$SArray",
                        "typeclass": "static_array",
                        "value_type": {"name": "Foo", "typeclass": "struct"},
                    },
                },
                "type": {
                    "length": 1,
                    "name": "$SArray",
                    "typeclass": "static_array",
                    "value_type": {"name": "Foo", "typeclass": "struct"},
                },
                "value": None,
            },
            {
                "annotation": {
                    "ast_type": "Subscript",
                    "node_id": 72,
                    "slice": {
                        "ast_type": "Tuple",
                        "elements": [
                            {"ast_type": "Name", "id": "Foo", "node_id": 76},
                            {"ast_type": "Int", "node_id": 78, "value": 5},
                        ],
                        "node_id": 75,
                    },
                    "value": {"ast_type": "Name", "id": "DynArray", "node_id": 73},
                },
                "ast_type": "VariableDecl",
                "is_constant": False,
                "is_immutable": False,
                "is_public": False,
                "is_transient": False,
                "node_id": 69,
                "target": {
                    "ast_type": "Name",
                    "id": "darray_var",
                    "node_id": 70,
                    "type": {
                        "length": 5,
                        "name": "DynArray",
                        "typeclass": "dynamic_array",
                        "value_type": {"name": "Foo", "typeclass": "struct"},
                    },
                },
                "type": {
                    "length": 5,
                    "name": "DynArray",
                    "typeclass": "dynamic_array",
                    "value_type": {"name": "Foo", "typeclass": "struct"},
                },
                "value": None,
            },
            {
                "annotation": {"ast_type": "Name", "id": "Qux", "node_id": 84},
                "ast_type": "VariableDecl",
                "is_constant": False,
                "is_immutable": False,
                "is_public": False,
                "is_transient": False,
                "node_id": 81,
                "target": {
                    "ast_type": "Name",
                    "id": "interface_var",
                    "node_id": 82,
                    "type": {
                        "name": "Qux",
                        "type_decl_node": {"node_id": 41, "source_id": 0},
                        "typeclass": "interface",
                    },
                },
                "type": {
                    "name": "Qux",
                    "type_decl_node": {"node_id": 41, "source_id": 0},
                    "typeclass": "interface",
                },
                "value": None,
            },
            {
                "annotation": {
                    "ast_type": "Subscript",
                    "node_id": 89,
                    "slice": {
                        "ast_type": "Tuple",
                        "elements": [
                            {"ast_type": "Name", "id": "address", "node_id": 93},
                            {"ast_type": "Name", "id": "Foo", "node_id": 95},
                        ],
                        "node_id": 92,
                    },
                    "value": {"ast_type": "Name", "id": "HashMap", "node_id": 90},
                },
                "ast_type": "VariableDecl",
                "is_constant": False,
                "is_immutable": False,
                "is_public": False,
                "is_transient": False,
                "node_id": 86,
                "target": {
                    "ast_type": "Name",
                    "id": "hashmap_var",
                    "node_id": 87,
                    "type": {
                        "key_type": {"name": "address"},
                        "name": "HashMap",
                        "typeclass": "hashmap",
                        "value_type": {"name": "Foo", "typeclass": "struct"},
                    },
                },
                "type": {
                    "key_type": {"name": "address"},
                    "name": "HashMap",
                    "typeclass": "hashmap",
                    "value_type": {"name": "Foo", "typeclass": "struct"},
                },
                "value": None,
            },
            {
                "annotation": {
                    "ast_type": "Subscript",
                    "node_id": 102,
                    "slice": {"ast_type": "Int", "node_id": 105, "value": 2},
                    "value": {"ast_type": "Name", "id": "uint256", "node_id": 103},
                },
                "ast_type": "VariableDecl",
                "is_constant": False,
                "is_immutable": False,
                "is_public": False,
                "is_transient": False,
                "node_id": 99,
                "target": {
                    "ast_type": "Name",
                    "id": "sarray_var2",
                    "node_id": 100,
                    "type": {
                        "length": 2,
                        "name": "$SArray",
                        "typeclass": "static_array",
                        "value_type": {
                            "bits": 256,
                            "is_signed": False,
                            "name": "uint256",
                            "typeclass": "integer",
                        },
                    },
                },
                "type": {
                    "length": 2,
                    "name": "$SArray",
                    "typeclass": "static_array",
                    "value_type": {
                        "bits": 256,
                        "is_signed": False,
                        "name": "uint256",
                        "typeclass": "integer",
                    },
                },
                "value": None,
            },
            {
                "annotation": {
                    "ast_type": "Subscript",
                    "node_id": 110,
                    "slice": {
                        "ast_type": "Tuple",
                        "elements": [
                            {"ast_type": "Name", "id": "uint256", "node_id": 114},
                            {"ast_type": "Int", "node_id": 116, "value": 5},
                        ],
                        "node_id": 113,
                    },
                    "value": {"ast_type": "Name", "id": "DynArray", "node_id": 111},
                },
                "ast_type": "VariableDecl",
                "is_constant": False,
                "is_immutable": False,
                "is_public": False,
                "is_transient": False,
                "node_id": 107,
                "target": {
                    "ast_type": "Name",
                    "id": "darray_var2",
                    "node_id": 108,
                    "type": {
                        "length": 5,
                        "name": "DynArray",
                        "typeclass": "dynamic_array",
                        "value_type": {
                            "bits": 256,
                            "is_signed": False,
                            "name": "uint256",
                            "typeclass": "integer",
                        },
                    },
                },
                "type": {
                    "length": 5,
                    "name": "DynArray",
                    "typeclass": "dynamic_array",
                    "value_type": {
                        "bits": 256,
                        "is_signed": False,
                        "name": "uint256",
                        "typeclass": "integer",
                    },
                },
                "value": None,
            },
            {
                "args": {
                    "args": [],
                    "ast_type": "arguments",
                    "default": None,
                    "defaults": [],
                    "node_id": 120,
                },
                "ast_type": "FunctionDef",
                "body": [
                    {
                        "annotation": {"ast_type": "Name", "id": "uint256", "node_id": 124},
                        "ast_type": "AnnAssign",
                        "node_id": 121,
                        "target": {
                            "ast_type": "Name",
                            "id": "t",
                            "node_id": 122,
                            "type": {
                                "bits": 256,
                                "is_signed": False,
                                "name": "uint256",
                                "typeclass": "integer",
                            },
                        },
                        "value": {
                            "args": [
                                {
                                    "ast_type": "Name",
                                    "id": "uint256",
                                    "node_id": 129,
                                    "type": {
                                        "type_t": {
                                            "bits": 256,
                                            "is_signed": False,
                                            "name": "uint256",
                                            "typeclass": "integer",
                                        }
                                    },
                                }
                            ],
                            "ast_type": "Call",
                            "func": {
                                "ast_type": "Name",
                                "id": "max_value",
                                "node_id": 127,
                                "type": {"name": "max_value", "typeclass": "builtin_function"},
                            },
                            "keywords": [],
                            "node_id": 126,
                            "type": {
                                "bits": 256,
                                "is_signed": False,
                                "name": "uint256",
                                "typeclass": "integer",
                            },
                        },
                    },
                    {
                        "annotation": {"ast_type": "Name", "id": "int24", "node_id": 134},
                        "ast_type": "AnnAssign",
                        "node_id": 131,
                        "target": {
                            "ast_type": "Name",
                            "id": "u",
                            "node_id": 132,
                            "type": {
                                "bits": 24,
                                "is_signed": True,
                                "name": "int24",
                                "typeclass": "integer",
                            },
                        },
                        "value": {
                            "args": [
                                {
                                    "ast_type": "Name",
                                    "id": "int24",
                                    "node_id": 139,
                                    "type": {
                                        "type_t": {
                                            "bits": 24,
                                            "is_signed": True,
                                            "name": "int24",
                                            "typeclass": "integer",
                                        }
                                    },
                                }
                            ],
                            "ast_type": "Call",
                            "func": {
                                "ast_type": "Name",
                                "id": "empty",
                                "node_id": 137,
                                "type": {"name": "empty", "typeclass": "builtin_function"},
                            },
                            "keywords": [],
                            "node_id": 136,
                            "type": {
                                "bits": 24,
                                "is_signed": True,
                                "name": "int24",
                                "typeclass": "integer",
                            },
                        },
                    },
                    {
                        "ast_type": "Assign",
                        "node_id": 141,
                        "target": {
                            "ast_type": "Attribute",
                            "attr": "foo_var",
                            "node_id": 142,
                            "type": {"name": "Foo", "typeclass": "struct"},
                            "value": {
                                "ast_type": "Name",
                                "id": "self",
                                "node_id": 143,
                                "type": {"name": "self"},
                            },
                        },
                        "value": {
                            "args": [
                                {
                                    "ast_type": "Name",
                                    "id": "Foo",
                                    "node_id": 149,
                                    "type": {"type_t": {"name": "Foo", "typeclass": "struct"}},
                                }
                            ],
                            "ast_type": "Call",
                            "func": {
                                "ast_type": "Name",
                                "id": "empty",
                                "node_id": 147,
                                "type": {"name": "empty", "typeclass": "builtin_function"},
                            },
                            "keywords": [],
                            "node_id": 146,
                            "type": {"name": "Foo", "typeclass": "struct"},
                        },
                    },
                    {
                        "ast_type": "Assign",
                        "node_id": 151,
                        "target": {
                            "ast_type": "Subscript",
                            "node_id": 152,
                            "slice": {
                                "ast_type": "Int",
                                "node_id": 157,
                                "type": {
                                    "bits": 8,
                                    "is_signed": True,
                                    "name": "int8",
                                    "typeclass": "integer",
                                },
                                "value": 0,
                            },
                            "type": {"name": "Foo", "typeclass": "struct"},
                            "value": {
                                "ast_type": "Attribute",
                                "attr": "sarray_var",
                                "node_id": 153,
                                "type": {
                                    "length": 1,
                                    "name": "$SArray",
                                    "typeclass": "static_array",
                                    "value_type": {"name": "Foo", "typeclass": "struct"},
                                },
                                "value": {
                                    "ast_type": "Name",
                                    "id": "self",
                                    "node_id": 154,
                                    "type": {"name": "self"},
                                },
                            },
                        },
                        "value": {
                            "args": [
                                {
                                    "ast_type": "Name",
                                    "id": "Foo",
                                    "node_id": 162,
                                    "type": {"type_t": {"name": "Foo", "typeclass": "struct"}},
                                }
                            ],
                            "ast_type": "Call",
                            "func": {
                                "ast_type": "Name",
                                "id": "empty",
                                "node_id": 160,
                                "type": {"name": "empty", "typeclass": "builtin_function"},
                            },
                            "keywords": [],
                            "node_id": 159,
                            "type": {"name": "Foo", "typeclass": "struct"},
                        },
                    },
                    {
                        "ast_type": "Assign",
                        "node_id": 164,
                        "target": {
                            "ast_type": "Subscript",
                            "node_id": 165,
                            "slice": {
                                "ast_type": "Int",
                                "node_id": 170,
                                "type": {
                                    "bits": 8,
                                    "is_signed": True,
                                    "name": "int8",
                                    "typeclass": "integer",
                                },
                                "value": 1,
                            },
                            "type": {"name": "Foo", "typeclass": "struct"},
                            "value": {
                                "ast_type": "Attribute",
                                "attr": "darray_var",
                                "node_id": 166,
                                "type": {
                                    "length": 5,
                                    "name": "DynArray",
                                    "typeclass": "dynamic_array",
                                    "value_type": {"name": "Foo", "typeclass": "struct"},
                                },
                                "value": {
                                    "ast_type": "Name",
                                    "id": "self",
                                    "node_id": 167,
                                    "type": {"name": "self"},
                                },
                            },
                        },
                        "value": {
                            "args": [
                                {
                                    "ast_type": "Name",
                                    "id": "Foo",
                                    "node_id": 175,
                                    "type": {"type_t": {"name": "Foo", "typeclass": "struct"}},
                                }
                            ],
                            "ast_type": "Call",
                            "func": {
                                "ast_type": "Name",
                                "id": "empty",
                                "node_id": 173,
                                "type": {"name": "empty", "typeclass": "builtin_function"},
                            },
                            "keywords": [],
                            "node_id": 172,
                            "type": {"name": "Foo", "typeclass": "struct"},
                        },
                    },
                    {
                        "ast_type": "Assign",
                        "node_id": 177,
                        "target": {
                            "ast_type": "Tuple",
                            "elements": [
                                {
                                    "ast_type": "Attribute",
                                    "attr": "sarray_var",
                                    "node_id": 179,
                                    "type": {
                                        "length": 1,
                                        "name": "$SArray",
                                        "typeclass": "static_array",
                                        "value_type": {"name": "Foo", "typeclass": "struct"},
                                    },
                                    "value": {
                                        "ast_type": "Name",
                                        "id": "self",
                                        "node_id": 180,
                                        "type": {"name": "self"},
                                    },
                                },
                                {
                                    "ast_type": "Name",
                                    "id": "t",
                                    "node_id": 183,
                                    "type": {
                                        "bits": 256,
                                        "is_signed": False,
                                        "name": "uint256",
                                        "typeclass": "integer",
                                    },
                                },
                            ],
                            "node_id": 178,
                            "type": {"members": {}, "name": "$Tuple", "typeclass": "tuple"},
                        },
                        "value": {
                            "ast_type": "ExtCall",
                            "node_id": 186,
                            "type": {"members": {}, "name": "$Tuple", "typeclass": "tuple"},
                            "value": {
                                "args": [],
                                "ast_type": "Call",
                                "func": {
                                    "ast_type": "Attribute",
                                    "attr": "return_tuple",
                                    "node_id": 188,
                                    "type": {
                                        "name": "return_tuple",
                                        "type_decl_node": {"node_id": 42, "source_id": 0},
                                        "typeclass": "contract_function",
                                    },
                                    "value": {
                                        "ast_type": "Attribute",
                                        "attr": "interface_var",
                                        "node_id": 189,
                                        "type": {
                                            "name": "Qux",
                                            "type_decl_node": {"node_id": 41, "source_id": 0},
                                            "typeclass": "interface",
                                        },
                                        "value": {
                                            "ast_type": "Name",
                                            "id": "self",
                                            "node_id": 190,
                                            "type": {"name": "self"},
                                        },
                                    },
                                },
                                "keywords": [],
                                "node_id": 187,
                                "type": {"members": {}, "name": "$Tuple", "typeclass": "tuple"},
                            },
                        },
                    },
                ],
                "decorator_list": [{"ast_type": "Name", "id": "internal", "node_id": 194}],
                "doc_string": None,
                "name": "foo",
                "node_id": 119,
                "pos": None,
                "returns": None,
            },
            {
                "args": {
                    "args": [],
                    "ast_type": "arguments",
                    "default": None,
                    "defaults": [],
                    "node_id": 197,
                },
                "ast_type": "FunctionDef",
                "body": [
                    {
                        "annotation": {"ast_type": "Name", "id": "bytes24", "node_id": 201},
                        "ast_type": "AnnAssign",
                        "node_id": 198,
                        "target": {
                            "ast_type": "Name",
                            "id": "s",
                            "node_id": 199,
                            "type": {"m": 24, "name": "bytes24", "typeclass": "bytes_m"},
                        },
                        "value": {
                            "args": [
                                {
                                    "ast_type": "Name",
                                    "id": "bytes24",
                                    "node_id": 206,
                                    "type": {
                                        "type_t": {
                                            "m": 24,
                                            "name": "bytes24",
                                            "typeclass": "bytes_m",
                                        }
                                    },
                                }
                            ],
                            "ast_type": "Call",
                            "func": {
                                "ast_type": "Name",
                                "id": "empty",
                                "node_id": 204,
                                "type": {"name": "empty", "typeclass": "builtin_function"},
                            },
                            "keywords": [],
                            "node_id": 203,
                            "type": {"m": 24, "name": "bytes24", "typeclass": "bytes_m"},
                        },
                    }
                ],
                "decorator_list": [{"ast_type": "Name", "id": "external", "node_id": 208}],
                "doc_string": None,
                "name": "bar",
                "node_id": 196,
                "pos": None,
                "returns": None,
            },
        ],
        "doc_string": None,
        "name": None,
        "node_id": 0,
        "path": "lib1.vy",
        "source_id": 0,
        "type": {
            "name": "lib1.vy",
            "type_decl_node": {"node_id": 0, "source_id": 0},
            "typeclass": "module",
        },
    }


def test_output_variable_read_write_analysis(make_input_bundle, chdir_tmp_path):
    # test we output the result of variable read/write correctly
    # note: also tests serialization of structs, strings, static arrays,
    # and type_decl_nodes across modules.
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
    main = """
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
    input_bundle = make_input_bundle({"lib1.vy": lib1, "main.vy": main})

    # preliminaries: main.vy has source_id==0, lib1.vy has source_id==1.
    file = input_bundle.load_file("main.vy")
    assert file.source_id == 0
    assert input_bundle.load_file("lib1.vy").source_id == 1

    out = compiler.compile_from_file_input(
        file, input_bundle=input_bundle, output_formats=["annotated_ast_dict"]
    )
    ast = out["annotated_ast_dict"]["ast"]

    assert ast["path"] == "main.vy"
    assert ast["source_id"] == 0

    _strip_source_annotations(ast, to_strip=NODE_SRC_ATTRIBUTES + ("node_id", "type"))

    foo, bar, baz, qux, qux2 = ast["body"][3:]
    assert foo["name"] == "foo"
    assert foo["body"] == [
        {
            "annotation": {"ast_type": "Name", "id": "uint256"},
            "ast_type": "AnnAssign",
            "target": {"ast_type": "Name", "id": "x"},
            "value": {
                "ast_type": "Attribute",
                "attr": "counter",
                "value": {"ast_type": "Name", "id": "lib1"},
                "variable_reads": [
                    {
                        "access_path": [],
                        "decl_node": {"node_id": 29, "source_id": 1},
                        "name": "counter",
                    }
                ],
            },
        },
        {
            "ast_type": "AugAssign",
            "op": {"ast_type": "Add"},
            "target": {
                "ast_type": "Attribute",
                "attr": "counter",
                "value": {"ast_type": "Name", "id": "lib1"},
                "variable_reads": [
                    {
                        "access_path": [],
                        "decl_node": {"node_id": 29, "source_id": 1},
                        "name": "counter",
                    }
                ],
                "variable_writes": [
                    {
                        "access_path": [],
                        "decl_node": {"node_id": 29, "source_id": 1},
                        "name": "counter",
                    }
                ],
            },
            "value": {"ast_type": "Int", "value": 1},
        },
    ]

    assert bar["name"] == "bar"
    assert bar["body"] == [
        {
            "annotation": {"ast_type": "Name", "id": "uint256"},
            "ast_type": "AnnAssign",
            "target": {"ast_type": "Name", "id": "x"},
            "value": {
                "ast_type": "Attribute",
                "attr": "counter",
                "value": {"ast_type": "Name", "id": "lib1"},
                "variable_reads": [
                    {
                        "access_path": [],
                        "decl_node": {"node_id": 29, "source_id": 1},
                        "name": "counter",
                    }
                ],
            },
        },
        {
            "annotation": {"ast_type": "Name", "id": "uint256"},
            "ast_type": "AnnAssign",
            "target": {"ast_type": "Name", "id": "y"},
            "value": {
                "ast_type": "Attribute",
                "attr": "counter",
                "value": {"ast_type": "Name", "id": "self"},
                "variable_reads": [
                    {
                        "access_path": [],
                        "decl_node": {"node_id": 8, "source_id": 0},
                        "name": "counter",
                    }
                ],
            },
        },
        {
            "ast_type": "AugAssign",
            "op": {"ast_type": "Add"},
            "target": {
                "ast_type": "Attribute",
                "attr": "counter",
                "value": {"ast_type": "Name", "id": "lib1"},
                "variable_reads": [
                    {
                        "access_path": [],
                        "decl_node": {"node_id": 29, "source_id": 1},
                        "name": "counter",
                    }
                ],
                "variable_writes": [
                    {
                        "access_path": [],
                        "decl_node": {"node_id": 29, "source_id": 1},
                        "name": "counter",
                    }
                ],
            },
            "value": {"ast_type": "Int", "value": 1},
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
                    "value": {"ast_type": "Name", "id": "self"},
                    "variable_reads": [
                        {
                            "access_path": [],
                            "decl_node": {"node_id": 29, "source_id": 1},
                            "name": "counter",
                        },
                        {
                            "access_path": [],
                            "decl_node": {"node_id": 8, "source_id": 0},
                            "name": "counter",
                        },
                    ],
                    "variable_writes": [
                        {
                            "access_path": [],
                            "decl_node": {"node_id": 29, "source_id": 1},
                            "name": "counter",
                        }
                    ],
                },
                "keywords": [],
            },
        },
        {
            "ast_type": "AugAssign",
            "op": {"ast_type": "Add"},
            "target": {
                "ast_type": "Attribute",
                "attr": "counter",
                "value": {"ast_type": "Name", "id": "self"},
                "variable_reads": [
                    {
                        "access_path": [],
                        "decl_node": {"node_id": 8, "source_id": 0},
                        "name": "counter",
                    }
                ],
                "variable_writes": [
                    {
                        "access_path": [],
                        "decl_node": {"node_id": 8, "source_id": 0},
                        "name": "counter",
                    }
                ],
            },
            "value": {"ast_type": "Int", "value": 1},
        },
    ]

    assert qux["name"] == "qux"
    assert qux["body"] == [
        {
            "ast_type": "Assign",
            "target": {
                "ast_type": "Attribute",
                "attr": "bars",
                "value": {"ast_type": "Name", "id": "lib1"},
                "variable_reads": [
                    {
                        "access_path": [],
                        "decl_node": {"node_id": 34, "source_id": 1},
                        "name": "bars",
                    }
                ],
                "variable_writes": [
                    {
                        "access_path": [],
                        "decl_node": {"node_id": 34, "source_id": 1},
                        "name": "bars",
                    }
                ],
            },
            "value": {"ast_type": "List", "elements": []},
        },
        {
            "ast_type": "Assign",
            "target": {
                "ast_type": "Subscript",
                "slice": {"ast_type": "Int", "value": 0},
                "value": {
                    "ast_type": "Attribute",
                    "attr": "bars",
                    "value": {"ast_type": "Name", "id": "lib1"},
                    "variable_reads": [
                        {
                            "access_path": [],
                            "decl_node": {"node_id": 34, "source_id": 1},
                            "name": "bars",
                        }
                    ],
                },
                "variable_reads": [
                    {
                        "access_path": ["$subscript_access"],
                        "decl_node": {"node_id": 34, "source_id": 1},
                        "name": "bars",
                    }
                ],
                "variable_writes": [
                    {
                        "access_path": ["$subscript_access"],
                        "decl_node": {"node_id": 34, "source_id": 1},
                        "name": "bars",
                    }
                ],
            },
            "value": {
                "args": [
                    {
                        "ast_type": "Attribute",
                        "attr": "Bar",
                        "value": {"ast_type": "Name", "id": "lib1"},
                    }
                ],
                "ast_type": "Call",
                "func": {"ast_type": "Name", "id": "empty"},
                "keywords": [],
            },
        },
        {
            "ast_type": "Assign",
            "target": {
                "ast_type": "Attribute",
                "attr": "items",
                "value": {
                    "ast_type": "Subscript",
                    "slice": {"ast_type": "Int", "value": 1},
                    "value": {
                        "ast_type": "Attribute",
                        "attr": "bars",
                        "value": {"ast_type": "Name", "id": "lib1"},
                        "variable_reads": [
                            {
                                "access_path": [],
                                "decl_node": {"node_id": 34, "source_id": 1},
                                "name": "bars",
                            }
                        ],
                    },
                    "variable_reads": [
                        {
                            "access_path": ["$subscript_access"],
                            "decl_node": {"node_id": 34, "source_id": 1},
                            "name": "bars",
                        }
                    ],
                },
                "variable_reads": [
                    {
                        "access_path": ["$subscript_access", "items"],
                        "decl_node": {"node_id": 34, "source_id": 1},
                        "name": "bars",
                    }
                ],
                "variable_writes": [
                    {
                        "access_path": ["$subscript_access", "items"],
                        "decl_node": {"node_id": 34, "source_id": 1},
                        "name": "bars",
                    }
                ],
            },
            "value": {
                "args": [
                    {
                        "ast_type": "Subscript",
                        "slice": {"ast_type": "Int", "value": 2},
                        "value": {
                            "ast_type": "Attribute",
                            "attr": "Foo",
                            "value": {"ast_type": "Name", "id": "lib1"},
                        },
                    }
                ],
                "ast_type": "Call",
                "func": {"ast_type": "Name", "id": "empty"},
                "keywords": [],
            },
        },
        {
            "ast_type": "Assign",
            "target": {
                "ast_type": "Attribute",
                "attr": "a",
                "value": {
                    "ast_type": "Subscript",
                    "slice": {"ast_type": "Int", "value": 0},
                    "value": {
                        "ast_type": "Attribute",
                        "attr": "items",
                        "value": {
                            "ast_type": "Subscript",
                            "slice": {"ast_type": "Int", "value": 1},
                            "value": {
                                "ast_type": "Attribute",
                                "attr": "bars",
                                "value": {"ast_type": "Name", "id": "lib1"},
                                "variable_reads": [
                                    {
                                        "access_path": [],
                                        "decl_node": {"node_id": 34, "source_id": 1},
                                        "name": "bars",
                                    }
                                ],
                            },
                            "variable_reads": [
                                {
                                    "access_path": ["$subscript_access"],
                                    "decl_node": {"node_id": 34, "source_id": 1},
                                    "name": "bars",
                                }
                            ],
                        },
                        "variable_reads": [
                            {
                                "access_path": ["$subscript_access", "items"],
                                "decl_node": {"node_id": 34, "source_id": 1},
                                "name": "bars",
                            }
                        ],
                    },
                    "variable_reads": [
                        {
                            "access_path": ["$subscript_access", "items", "$subscript_access"],
                            "decl_node": {"node_id": 34, "source_id": 1},
                            "name": "bars",
                        }
                    ],
                },
                "variable_reads": [
                    {
                        "access_path": ["$subscript_access", "items", "$subscript_access", "a"],
                        "decl_node": {"node_id": 34, "source_id": 1},
                        "name": "bars",
                    }
                ],
                "variable_writes": [
                    {
                        "access_path": ["$subscript_access", "items", "$subscript_access", "a"],
                        "decl_node": {"node_id": 34, "source_id": 1},
                        "name": "bars",
                    }
                ],
            },
            "value": {"ast_type": "Int", "value": 1},
        },
        {
            "ast_type": "Assign",
            "target": {
                "ast_type": "Attribute",
                "attr": "c",
                "value": {
                    "ast_type": "Subscript",
                    "slice": {"ast_type": "Int", "value": 1},
                    "value": {
                        "ast_type": "Attribute",
                        "attr": "items",
                        "value": {
                            "ast_type": "Subscript",
                            "slice": {"ast_type": "Int", "value": 0},
                            "value": {
                                "ast_type": "Attribute",
                                "attr": "bars",
                                "value": {"ast_type": "Name", "id": "lib1"},
                                "variable_reads": [
                                    {
                                        "access_path": [],
                                        "decl_node": {"node_id": 34, "source_id": 1},
                                        "name": "bars",
                                    }
                                ],
                            },
                            "variable_reads": [
                                {
                                    "access_path": ["$subscript_access"],
                                    "decl_node": {"node_id": 34, "source_id": 1},
                                    "name": "bars",
                                }
                            ],
                        },
                        "variable_reads": [
                            {
                                "access_path": ["$subscript_access", "items"],
                                "decl_node": {"node_id": 34, "source_id": 1},
                                "name": "bars",
                            }
                        ],
                    },
                    "variable_reads": [
                        {
                            "access_path": ["$subscript_access", "items", "$subscript_access"],
                            "decl_node": {"node_id": 34, "source_id": 1},
                            "name": "bars",
                        }
                    ],
                },
                "variable_reads": [
                    {
                        "access_path": ["$subscript_access", "items", "$subscript_access", "c"],
                        "decl_node": {"node_id": 34, "source_id": 1},
                        "name": "bars",
                    }
                ],
                "variable_writes": [
                    {
                        "access_path": ["$subscript_access", "items", "$subscript_access", "c"],
                        "decl_node": {"node_id": 34, "source_id": 1},
                        "name": "bars",
                    }
                ],
            },
            "value": {"ast_type": "Decimal", "value": "10.0"},
        },
    ]

    assert qux2["name"] == "qux2"
    assert qux2["body"] == [
        {
            "ast_type": "Expr",
            "value": {
                "args": [],
                "ast_type": "Call",
                "func": {
                    "ast_type": "Attribute",
                    "attr": "qux",
                    "value": {"ast_type": "Name", "id": "self"},
                    "variable_reads": [
                        {
                            "access_path": [],
                            "decl_node": {"node_id": 34, "source_id": 1},
                            "name": "bars",
                        },
                        {
                            "access_path": ["$subscript_access"],
                            "decl_node": {"node_id": 34, "source_id": 1},
                            "name": "bars",
                        },
                        {
                            "access_path": ["$subscript_access", "items"],
                            "decl_node": {"node_id": 34, "source_id": 1},
                            "name": "bars",
                        },
                        {
                            "access_path": ["$subscript_access", "items", "$subscript_access"],
                            "decl_node": {"node_id": 34, "source_id": 1},
                            "name": "bars",
                        },
                        {
                            "access_path": ["$subscript_access", "items", "$subscript_access", "a"],
                            "decl_node": {"node_id": 34, "source_id": 1},
                            "name": "bars",
                        },
                        {
                            "access_path": ["$subscript_access", "items", "$subscript_access", "c"],
                            "decl_node": {"node_id": 34, "source_id": 1},
                            "name": "bars",
                        },
                    ],
                    "variable_writes": [
                        {
                            "access_path": [],
                            "decl_node": {"node_id": 34, "source_id": 1},
                            "name": "bars",
                        },
                        {
                            "access_path": ["$subscript_access"],
                            "decl_node": {"node_id": 34, "source_id": 1},
                            "name": "bars",
                        },
                        {
                            "access_path": ["$subscript_access", "items"],
                            "decl_node": {"node_id": 34, "source_id": 1},
                            "name": "bars",
                        },
                        {
                            "access_path": ["$subscript_access", "items", "$subscript_access", "a"],
                            "decl_node": {"node_id": 34, "source_id": 1},
                            "name": "bars",
                        },
                        {
                            "access_path": ["$subscript_access", "items", "$subscript_access", "c"],
                            "decl_node": {"node_id": 34, "source_id": 1},
                            "name": "bars",
                        },
                    ],
                },
                "keywords": [],
            },
        }
    ]

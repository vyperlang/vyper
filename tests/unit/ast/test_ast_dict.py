import copy
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
            "node_id": 3,
            "end_lineno": 2,
            "lineno": 2,
            "end_col_offset": 9,
            "src": "4:6:0",
            "ast_type": "Name",
            "col_offset": 3,
            "id": "int128",
        },
        "node_id": 1,
        "end_lineno": 2,
        "end_col_offset": 9,
        "is_transient": False,
        "lineno": 2,
        "src": "1:9:0",
        "is_public": False,
        "value": None,
        "ast_type": "VariableDecl",
        "is_constant": False,
        "col_offset": 0,
        "target": {
            "node_id": 2,
            "end_lineno": 2,
            "lineno": 2,
            "end_col_offset": 1,
            "src": "1:1:0",
            "ast_type": "Name",
            "col_offset": 0,
            "id": "a",
            "type": {"is_signed": True, "bits": 128, "name": "int128", "typeclass": "integer"},
        },
        "is_immutable": False,
        "type": {"is_signed": True, "bits": 128, "name": "int128", "typeclass": "integer"},
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
        "end_lineno": 5,
        "node_id": 7,
        "col_offset": 0,
        "end_col_offset": 15,
        "src": "48:15:0",
        "annotation": {
            "id": "Foo",
            "end_lineno": 5,
            "node_id": 9,
            "col_offset": 12,
            "end_col_offset": 15,
            "src": "60:3:0",
            "lineno": 5,
            "ast_type": "Name",
        },
        "lineno": 5,
        "ast_type": "ImplementsDecl",
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
    lib1_out = compiler.compile_from_file_input(
        lib1_file, input_bundle=input_bundle, output_formats=["annotated_ast_dict"]
    )

    lib1_ast = copy.deepcopy(lib1_out["annotated_ast_dict"]["ast"])
    lib1_sha256sum = lib1_ast.pop("source_sha256sum")
    assert lib1_sha256sum == lib1_file.sha256sum
    to_strip = NODE_SRC_ATTRIBUTES + ("resolved_path", "variable_reads", "variable_writes")
    _strip_source_annotations(lib1_ast, to_strip=to_strip)

    main_file = input_bundle.load_file("main.vy")
    main_out = compiler.compile_from_file_input(
        main_file, input_bundle=input_bundle, output_formats=["annotated_ast_dict"]
    )
    main_ast = main_out["annotated_ast_dict"]["ast"]
    main_sha256sum = main_ast.pop("source_sha256sum")
    assert main_sha256sum == main_file.sha256sum
    _strip_source_annotations(main_ast, to_strip=to_strip)

    assert main_out["annotated_ast_dict"]["imports"][0] == lib1_out["annotated_ast_dict"]["ast"]

    # TODO: would be nice to refactor this into bunch of small test cases
    assert main_ast == {
        "node_id": 0,
        "path": "main.vy",
        "body": [
            {
                "alias": None,
                "node_id": 1,
                "name": "lib1",
                "ast_type": "Import",
                "import_info": {
                    "alias": "lib1",
                    "qualified_module_name": "lib1",
                    "source_id": 0,
                    "path": "lib1.vy",
                    "file_sha256sum": lib1_sha256sum,
                },
            },
            {
                "node_id": 3,
                "annotation": {"node_id": 5, "id": "lib1", "ast_type": "Name"},
                "ast_type": "InitializesDecl",
            },
            {
                "node_id": 6,
                "returns": None,
                "pos": None,
                "body": [
                    {
                        "node_id": 8,
                        "value": {
                            "node_id": 9,
                            "keywords": [],
                            "args": [],
                            "func": {
                                "attr": "foo",
                                "node_id": 10,
                                "value": {
                                    "node_id": 11,
                                    "id": "lib1",
                                    "ast_type": "Name",
                                    "type": {
                                        "name": "lib1.vy",
                                        "type_decl_node": {"node_id": 0, "source_id": 0},
                                        "typeclass": "module",
                                    },
                                },
                                "ast_type": "Attribute",
                                "type": {
                                    "name": "foo",
                                    "type_decl_node": {"node_id": 74, "source_id": 0},
                                    "typeclass": "contract_function",
                                },
                            },
                            "ast_type": "Call",
                            "type": {"name": "(void)"},
                        },
                        "ast_type": "Expr",
                    },
                    {
                        "node_id": 13,
                        "value": {
                            "node_id": 14,
                            "keywords": [],
                            "args": [],
                            "func": {
                                "attr": "Bar",
                                "node_id": 15,
                                "value": {
                                    "node_id": 16,
                                    "id": "lib1",
                                    "ast_type": "Name",
                                    "type": {
                                        "name": "lib1.vy",
                                        "type_decl_node": {"node_id": 0, "source_id": 0},
                                        "typeclass": "module",
                                    },
                                },
                                "ast_type": "Attribute",
                                "type": {
                                    "type_t": {
                                        "name": "Bar",
                                        "type_decl_node": {"node_id": 5, "source_id": 0},
                                        "typeclass": "event",
                                    }
                                },
                            },
                            "ast_type": "Call",
                            "type": {"name": "(void)"},
                        },
                        "ast_type": "Log",
                        "type": {
                            "name": "Bar",
                            "type_decl_node": {"node_id": 5, "source_id": 0},
                            "typeclass": "event",
                        },
                    },
                    {
                        "node_id": 17,
                        "annotation": {
                            "attr": "Foo",
                            "node_id": 19,
                            "value": {"node_id": 20, "id": "lib1", "ast_type": "Name"},
                            "ast_type": "Attribute",
                        },
                        "value": {
                            "node_id": 21,
                            "keywords": [],
                            "args": [
                                {
                                    "attr": "Foo",
                                    "node_id": 23,
                                    "value": {
                                        "node_id": 24,
                                        "id": "lib1",
                                        "ast_type": "Name",
                                        "type": {
                                            "name": "lib1.vy",
                                            "type_decl_node": {"node_id": 0, "source_id": 0},
                                            "typeclass": "module",
                                        },
                                    },
                                    "ast_type": "Attribute",
                                    "type": {"type_t": {"name": "Foo", "typeclass": "struct"}},
                                }
                            ],
                            "func": {
                                "node_id": 22,
                                "id": "empty",
                                "ast_type": "Name",
                                "type": {"name": "empty", "typeclass": "builtin_function"},
                            },
                            "ast_type": "Call",
                            "type": {"name": "Foo", "typeclass": "struct"},
                        },
                        "ast_type": "AnnAssign",
                        "target": {
                            "node_id": 18,
                            "id": "s",
                            "ast_type": "Name",
                            "type": {"name": "Foo", "typeclass": "struct"},
                        },
                    },
                ],
                "decorator_list": [{"node_id": 25, "id": "internal", "ast_type": "Name"}],
                "args": {
                    "node_id": 7,
                    "args": [],
                    "defaults": [],
                    "ast_type": "arguments",
                    "default": None,
                },
                "name": "foo",
                "doc_string": None,
                "ast_type": "FunctionDef",
            },
        ],
        "doc_string": None,
        "name": None,
        "source_id": 1,
        "ast_type": "Module",
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
        "path": "lib1.vy",
        "node_id": 0,
        "source_id": 0,
        "doc_string": None,
        "body": [
            {
                "node_id": 1,
                "doc_string": None,
                "body": [
                    {
                        "node_id": 2,
                        "target": {"node_id": 3, "id": "x", "ast_type": "Name"},
                        "ast_type": "AnnAssign",
                        "value": None,
                        "annotation": {"node_id": 4, "id": "uint256", "ast_type": "Name"},
                    }
                ],
                "ast_type": "StructDef",
                "name": "Foo",
            },
            {
                "node_id": 5,
                "doc_string": None,
                "body": [{"node_id": 6, "ast_type": "Pass"}],
                "ast_type": "EventDef",
                "name": "Bar",
            },
            {
                "node_id": 7,
                "doc_string": None,
                "body": [
                    {
                        "node_id": 8,
                        "target": {"node_id": 9, "id": "x", "ast_type": "Name"},
                        "ast_type": "AnnAssign",
                        "value": None,
                        "annotation": {"node_id": 10, "id": "decimal", "ast_type": "Name"},
                    },
                    {
                        "node_id": 11,
                        "target": {"node_id": 12, "id": "y", "ast_type": "Name"},
                        "ast_type": "AnnAssign",
                        "value": None,
                        "annotation": {
                            "node_id": 13,
                            "slice": {"node_id": 15, "ast_type": "Int", "value": 20},
                            "ast_type": "Subscript",
                            "value": {"node_id": 14, "id": "Bytes", "ast_type": "Name"},
                        },
                    },
                    {
                        "node_id": 16,
                        "target": {"node_id": 17, "id": "z", "ast_type": "Name"},
                        "ast_type": "AnnAssign",
                        "value": None,
                        "annotation": {
                            "node_id": 18,
                            "slice": {"node_id": 20, "ast_type": "Int", "value": 32},
                            "ast_type": "Subscript",
                            "value": {"node_id": 19, "id": "String", "ast_type": "Name"},
                        },
                    },
                    {
                        "node_id": 21,
                        "target": {"node_id": 22, "id": "w", "ast_type": "Name"},
                        "ast_type": "AnnAssign",
                        "value": None,
                        "annotation": {"node_id": 23, "id": "uint256", "ast_type": "Name"},
                    },
                    {
                        "node_id": 24,
                        "target": {"node_id": 25, "id": "u", "ast_type": "Name"},
                        "ast_type": "AnnAssign",
                        "value": None,
                        "annotation": {"node_id": 26, "id": "address", "ast_type": "Name"},
                    },
                ],
                "ast_type": "StructDef",
                "name": "Baz",
            },
            {
                "node_id": 27,
                "doc_string": None,
                "body": [
                    {
                        "node_id": 28,
                        "decorator_list": [],
                        "args": {
                            "node_id": 29,
                            "args": [],
                            "default": None,
                            "defaults": [],
                            "ast_type": "arguments",
                        },
                        "doc_string": None,
                        "returns": {
                            "node_id": 32,
                            "elements": [
                                {
                                    "node_id": 33,
                                    "slice": {"node_id": 35, "ast_type": "Int", "value": 1},
                                    "ast_type": "Subscript",
                                    "value": {"node_id": 34, "id": "Foo", "ast_type": "Name"},
                                },
                                {"node_id": 36, "id": "uint256", "ast_type": "Name"},
                            ],
                            "ast_type": "Tuple",
                        },
                        "pos": None,
                        "body": [
                            {
                                "node_id": 30,
                                "ast_type": "Expr",
                                "value": {"node_id": 31, "id": "nonpayable", "ast_type": "Name"},
                            }
                        ],
                        "ast_type": "FunctionDef",
                        "name": "return_tuple",
                    }
                ],
                "ast_type": "InterfaceDef",
                "name": "Qux",
            },
            {
                "node_id": 37,
                "target": {
                    "node_id": 38,
                    "id": "foo_var",
                    "ast_type": "Name",
                    "type": {"name": "Foo", "typeclass": "struct"},
                },
                "is_constant": False,
                "is_transient": False,
                "is_immutable": False,
                "ast_type": "VariableDecl",
                "value": None,
                "is_public": False,
                "annotation": {"node_id": 39, "id": "Foo", "ast_type": "Name"},
                "type": {"name": "Foo", "typeclass": "struct"},
            },
            {
                "node_id": 40,
                "target": {
                    "node_id": 41,
                    "id": "sarray_var",
                    "ast_type": "Name",
                    "type": {
                        "value_type": {"name": "Foo", "typeclass": "struct"},
                        "length": 1,
                        "name": "$SArray",
                        "typeclass": "static_array",
                    },
                },
                "is_constant": False,
                "is_transient": False,
                "is_immutable": False,
                "ast_type": "VariableDecl",
                "value": None,
                "is_public": False,
                "annotation": {
                    "node_id": 42,
                    "slice": {"node_id": 44, "ast_type": "Int", "value": 1},
                    "ast_type": "Subscript",
                    "value": {"node_id": 43, "id": "Foo", "ast_type": "Name"},
                },
                "type": {
                    "value_type": {"name": "Foo", "typeclass": "struct"},
                    "length": 1,
                    "name": "$SArray",
                    "typeclass": "static_array",
                },
            },
            {
                "node_id": 45,
                "target": {
                    "node_id": 46,
                    "id": "darray_var",
                    "ast_type": "Name",
                    "type": {
                        "value_type": {"name": "Foo", "typeclass": "struct"},
                        "length": 5,
                        "name": "DynArray",
                        "typeclass": "dynamic_array",
                    },
                },
                "is_constant": False,
                "is_transient": False,
                "is_immutable": False,
                "ast_type": "VariableDecl",
                "value": None,
                "is_public": False,
                "annotation": {
                    "node_id": 47,
                    "slice": {
                        "node_id": 49,
                        "elements": [
                            {"node_id": 50, "id": "Foo", "ast_type": "Name"},
                            {"node_id": 51, "ast_type": "Int", "value": 5},
                        ],
                        "ast_type": "Tuple",
                    },
                    "ast_type": "Subscript",
                    "value": {"node_id": 48, "id": "DynArray", "ast_type": "Name"},
                },
                "type": {
                    "value_type": {"name": "Foo", "typeclass": "struct"},
                    "length": 5,
                    "name": "DynArray",
                    "typeclass": "dynamic_array",
                },
            },
            {
                "node_id": 52,
                "target": {
                    "node_id": 53,
                    "id": "interface_var",
                    "ast_type": "Name",
                    "type": {
                        "name": "Qux",
                        "type_decl_node": {"node_id": 27, "source_id": 0},
                        "typeclass": "interface",
                    },
                },
                "is_constant": False,
                "is_transient": False,
                "is_immutable": False,
                "ast_type": "VariableDecl",
                "value": None,
                "is_public": False,
                "annotation": {"node_id": 54, "id": "Qux", "ast_type": "Name"},
                "type": {
                    "name": "Qux",
                    "type_decl_node": {"node_id": 27, "source_id": 0},
                    "typeclass": "interface",
                },
            },
            {
                "node_id": 55,
                "target": {
                    "node_id": 56,
                    "id": "hashmap_var",
                    "ast_type": "Name",
                    "type": {
                        "key_type": {"name": "address"},
                        "value_type": {"name": "Foo", "typeclass": "struct"},
                        "name": "HashMap",
                        "typeclass": "hashmap",
                    },
                },
                "is_constant": False,
                "is_transient": False,
                "is_immutable": False,
                "ast_type": "VariableDecl",
                "value": None,
                "is_public": False,
                "annotation": {
                    "node_id": 57,
                    "slice": {
                        "node_id": 59,
                        "elements": [
                            {"node_id": 60, "id": "address", "ast_type": "Name"},
                            {"node_id": 61, "id": "Foo", "ast_type": "Name"},
                        ],
                        "ast_type": "Tuple",
                    },
                    "ast_type": "Subscript",
                    "value": {"node_id": 58, "id": "HashMap", "ast_type": "Name"},
                },
                "type": {
                    "key_type": {"name": "address"},
                    "value_type": {"name": "Foo", "typeclass": "struct"},
                    "name": "HashMap",
                    "typeclass": "hashmap",
                },
            },
            {
                "node_id": 62,
                "target": {
                    "node_id": 63,
                    "id": "sarray_var2",
                    "ast_type": "Name",
                    "type": {
                        "value_type": {
                            "is_signed": False,
                            "bits": 256,
                            "name": "uint256",
                            "typeclass": "integer",
                        },
                        "length": 2,
                        "name": "$SArray",
                        "typeclass": "static_array",
                    },
                },
                "is_constant": False,
                "is_transient": False,
                "is_immutable": False,
                "ast_type": "VariableDecl",
                "value": None,
                "is_public": False,
                "annotation": {
                    "node_id": 64,
                    "slice": {"node_id": 66, "ast_type": "Int", "value": 2},
                    "ast_type": "Subscript",
                    "value": {"node_id": 65, "id": "uint256", "ast_type": "Name"},
                },
                "type": {
                    "value_type": {
                        "is_signed": False,
                        "bits": 256,
                        "name": "uint256",
                        "typeclass": "integer",
                    },
                    "length": 2,
                    "name": "$SArray",
                    "typeclass": "static_array",
                },
            },
            {
                "node_id": 67,
                "target": {
                    "node_id": 68,
                    "id": "darray_var2",
                    "ast_type": "Name",
                    "type": {
                        "value_type": {
                            "is_signed": False,
                            "bits": 256,
                            "name": "uint256",
                            "typeclass": "integer",
                        },
                        "length": 5,
                        "name": "DynArray",
                        "typeclass": "dynamic_array",
                    },
                },
                "is_constant": False,
                "is_transient": False,
                "is_immutable": False,
                "ast_type": "VariableDecl",
                "value": None,
                "is_public": False,
                "annotation": {
                    "node_id": 69,
                    "slice": {
                        "node_id": 71,
                        "elements": [
                            {"node_id": 72, "id": "uint256", "ast_type": "Name"},
                            {"node_id": 73, "ast_type": "Int", "value": 5},
                        ],
                        "ast_type": "Tuple",
                    },
                    "ast_type": "Subscript",
                    "value": {"node_id": 70, "id": "DynArray", "ast_type": "Name"},
                },
                "type": {
                    "value_type": {
                        "is_signed": False,
                        "bits": 256,
                        "name": "uint256",
                        "typeclass": "integer",
                    },
                    "length": 5,
                    "name": "DynArray",
                    "typeclass": "dynamic_array",
                },
            },
            {
                "node_id": 74,
                "decorator_list": [{"node_id": 120, "id": "internal", "ast_type": "Name"}],
                "args": {
                    "node_id": 75,
                    "args": [],
                    "default": None,
                    "defaults": [],
                    "ast_type": "arguments",
                },
                "doc_string": None,
                "returns": None,
                "pos": None,
                "body": [
                    {
                        "node_id": 76,
                        "target": {
                            "node_id": 77,
                            "id": "t",
                            "ast_type": "Name",
                            "type": {
                                "is_signed": False,
                                "bits": 256,
                                "name": "uint256",
                                "typeclass": "integer",
                            },
                        },
                        "ast_type": "AnnAssign",
                        "value": {
                            "node_id": 79,
                            "args": [
                                {
                                    "node_id": 81,
                                    "id": "uint256",
                                    "ast_type": "Name",
                                    "type": {
                                        "type_t": {
                                            "is_signed": False,
                                            "bits": 256,
                                            "name": "uint256",
                                            "typeclass": "integer",
                                        }
                                    },
                                }
                            ],
                            "func": {
                                "node_id": 80,
                                "id": "max_value",
                                "ast_type": "Name",
                                "type": {"name": "max_value", "typeclass": "builtin_function"},
                            },
                            "ast_type": "Call",
                            "keywords": [],
                            "type": {
                                "is_signed": False,
                                "bits": 256,
                                "name": "uint256",
                                "typeclass": "integer",
                            },
                        },
                        "annotation": {"node_id": 78, "id": "uint256", "ast_type": "Name"},
                    },
                    {
                        "node_id": 82,
                        "target": {
                            "node_id": 83,
                            "id": "u",
                            "ast_type": "Name",
                            "type": {
                                "is_signed": True,
                                "bits": 24,
                                "name": "int24",
                                "typeclass": "integer",
                            },
                        },
                        "ast_type": "AnnAssign",
                        "value": {
                            "node_id": 85,
                            "args": [
                                {
                                    "node_id": 87,
                                    "id": "int24",
                                    "ast_type": "Name",
                                    "type": {
                                        "type_t": {
                                            "is_signed": True,
                                            "bits": 24,
                                            "name": "int24",
                                            "typeclass": "integer",
                                        }
                                    },
                                }
                            ],
                            "func": {
                                "node_id": 86,
                                "id": "empty",
                                "ast_type": "Name",
                                "type": {"name": "empty", "typeclass": "builtin_function"},
                            },
                            "ast_type": "Call",
                            "keywords": [],
                            "type": {
                                "is_signed": True,
                                "bits": 24,
                                "name": "int24",
                                "typeclass": "integer",
                            },
                        },
                        "annotation": {"node_id": 84, "id": "int24", "ast_type": "Name"},
                    },
                    {
                        "node_id": 88,
                        "target": {
                            "node_id": 89,
                            "attr": "foo_var",
                            "ast_type": "Attribute",
                            "value": {
                                "node_id": 90,
                                "id": "self",
                                "ast_type": "Name",
                                "type": {"name": "self"},
                            },
                            "type": {"name": "Foo", "typeclass": "struct"},
                        },
                        "ast_type": "Assign",
                        "value": {
                            "node_id": 91,
                            "args": [
                                {
                                    "node_id": 93,
                                    "id": "Foo",
                                    "ast_type": "Name",
                                    "type": {"type_t": {"name": "Foo", "typeclass": "struct"}},
                                }
                            ],
                            "func": {
                                "node_id": 92,
                                "id": "empty",
                                "ast_type": "Name",
                                "type": {"name": "empty", "typeclass": "builtin_function"},
                            },
                            "ast_type": "Call",
                            "keywords": [],
                            "type": {"name": "Foo", "typeclass": "struct"},
                        },
                    },
                    {
                        "node_id": 94,
                        "target": {
                            "node_id": 95,
                            "slice": {
                                "node_id": 98,
                                "ast_type": "Int",
                                "value": 0,
                                "type": {
                                    "is_signed": True,
                                    "bits": 8,
                                    "name": "int8",
                                    "typeclass": "integer",
                                },
                            },
                            "ast_type": "Subscript",
                            "value": {
                                "node_id": 96,
                                "attr": "sarray_var",
                                "ast_type": "Attribute",
                                "value": {
                                    "node_id": 97,
                                    "id": "self",
                                    "ast_type": "Name",
                                    "type": {"name": "self"},
                                },
                                "type": {
                                    "value_type": {"name": "Foo", "typeclass": "struct"},
                                    "length": 1,
                                    "name": "$SArray",
                                    "typeclass": "static_array",
                                },
                            },
                            "type": {"name": "Foo", "typeclass": "struct"},
                        },
                        "ast_type": "Assign",
                        "value": {
                            "node_id": 99,
                            "args": [
                                {
                                    "node_id": 101,
                                    "id": "Foo",
                                    "ast_type": "Name",
                                    "type": {"type_t": {"name": "Foo", "typeclass": "struct"}},
                                }
                            ],
                            "func": {
                                "node_id": 100,
                                "id": "empty",
                                "ast_type": "Name",
                                "type": {"name": "empty", "typeclass": "builtin_function"},
                            },
                            "ast_type": "Call",
                            "keywords": [],
                            "type": {"name": "Foo", "typeclass": "struct"},
                        },
                    },
                    {
                        "node_id": 102,
                        "target": {
                            "node_id": 103,
                            "slice": {
                                "node_id": 106,
                                "ast_type": "Int",
                                "value": 1,
                                "type": {
                                    "is_signed": True,
                                    "bits": 8,
                                    "name": "int8",
                                    "typeclass": "integer",
                                },
                            },
                            "ast_type": "Subscript",
                            "value": {
                                "node_id": 104,
                                "attr": "darray_var",
                                "ast_type": "Attribute",
                                "value": {
                                    "node_id": 105,
                                    "id": "self",
                                    "ast_type": "Name",
                                    "type": {"name": "self"},
                                },
                                "type": {
                                    "value_type": {"name": "Foo", "typeclass": "struct"},
                                    "length": 5,
                                    "name": "DynArray",
                                    "typeclass": "dynamic_array",
                                },
                            },
                            "type": {"name": "Foo", "typeclass": "struct"},
                        },
                        "ast_type": "Assign",
                        "value": {
                            "node_id": 107,
                            "args": [
                                {
                                    "node_id": 109,
                                    "id": "Foo",
                                    "ast_type": "Name",
                                    "type": {"type_t": {"name": "Foo", "typeclass": "struct"}},
                                }
                            ],
                            "func": {
                                "node_id": 108,
                                "id": "empty",
                                "ast_type": "Name",
                                "type": {"name": "empty", "typeclass": "builtin_function"},
                            },
                            "ast_type": "Call",
                            "keywords": [],
                            "type": {"name": "Foo", "typeclass": "struct"},
                        },
                    },
                    {
                        "node_id": 110,
                        "target": {
                            "node_id": 111,
                            "elements": [
                                {
                                    "node_id": 112,
                                    "attr": "sarray_var",
                                    "ast_type": "Attribute",
                                    "value": {
                                        "node_id": 113,
                                        "id": "self",
                                        "ast_type": "Name",
                                        "type": {"name": "self"},
                                    },
                                    "type": {
                                        "value_type": {"name": "Foo", "typeclass": "struct"},
                                        "length": 1,
                                        "name": "$SArray",
                                        "typeclass": "static_array",
                                    },
                                },
                                {
                                    "node_id": 114,
                                    "id": "t",
                                    "ast_type": "Name",
                                    "type": {
                                        "is_signed": False,
                                        "bits": 256,
                                        "name": "uint256",
                                        "typeclass": "integer",
                                    },
                                },
                            ],
                            "ast_type": "Tuple",
                            "type": {"members": {}, "name": "$Tuple", "typeclass": "tuple"},
                        },
                        "ast_type": "Assign",
                        "value": {
                            "node_id": 115,
                            "ast_type": "ExtCall",
                            "value": {
                                "node_id": 116,
                                "args": [],
                                "func": {
                                    "node_id": 117,
                                    "attr": "return_tuple",
                                    "ast_type": "Attribute",
                                    "value": {
                                        "node_id": 118,
                                        "attr": "interface_var",
                                        "ast_type": "Attribute",
                                        "value": {
                                            "node_id": 119,
                                            "id": "self",
                                            "ast_type": "Name",
                                            "type": {"name": "self"},
                                        },
                                        "type": {
                                            "name": "Qux",
                                            "type_decl_node": {"node_id": 27, "source_id": 0},
                                            "typeclass": "interface",
                                        },
                                    },
                                    "type": {
                                        "name": "return_tuple",
                                        "type_decl_node": {"node_id": 28, "source_id": 0},
                                        "typeclass": "contract_function",
                                    },
                                },
                                "ast_type": "Call",
                                "keywords": [],
                                "type": {"members": {}, "name": "$Tuple", "typeclass": "tuple"},
                            },
                            "type": {"members": {}, "name": "$Tuple", "typeclass": "tuple"},
                        },
                    },
                ],
                "ast_type": "FunctionDef",
                "name": "foo",
            },
            {
                "node_id": 121,
                "decorator_list": [{"node_id": 129, "id": "external", "ast_type": "Name"}],
                "args": {
                    "node_id": 122,
                    "args": [],
                    "default": None,
                    "defaults": [],
                    "ast_type": "arguments",
                },
                "doc_string": None,
                "returns": None,
                "pos": None,
                "body": [
                    {
                        "node_id": 123,
                        "target": {
                            "node_id": 124,
                            "id": "s",
                            "ast_type": "Name",
                            "type": {"m": 24, "name": "bytes24", "typeclass": "bytes_m"},
                        },
                        "ast_type": "AnnAssign",
                        "value": {
                            "node_id": 126,
                            "args": [
                                {
                                    "node_id": 128,
                                    "id": "bytes24",
                                    "ast_type": "Name",
                                    "type": {
                                        "type_t": {
                                            "m": 24,
                                            "name": "bytes24",
                                            "typeclass": "bytes_m",
                                        }
                                    },
                                }
                            ],
                            "func": {
                                "node_id": 127,
                                "id": "empty",
                                "ast_type": "Name",
                                "type": {"name": "empty", "typeclass": "builtin_function"},
                            },
                            "ast_type": "Call",
                            "keywords": [],
                            "type": {"m": 24, "name": "bytes24", "typeclass": "bytes_m"},
                        },
                        "annotation": {"node_id": 125, "id": "bytes24", "ast_type": "Name"},
                    }
                ],
                "ast_type": "FunctionDef",
                "name": "bar",
            },
        ],
        "ast_type": "Module",
        "name": None,
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
            "value": {
                "attr": "counter",
                "value": {"id": "lib1", "ast_type": "Name"},
                "ast_type": "Attribute",
                "variable_reads": [
                    {
                        "name": "counter",
                        "decl_node": {"node_id": 19, "source_id": 1},
                        "access_path": [],
                    }
                ],
            },
            "ast_type": "AnnAssign",
            "target": {
                "id": "x",
                "ast_type": "Name",
                "variable_reads": [
                    {"name": "x", "decl_node": {"node_id": 11, "source_id": 0}, "access_path": []}
                ],
            },
            "annotation": {"id": "uint256", "ast_type": "Name"},
        },
        {
            "value": {"value": 1, "ast_type": "Int"},
            "ast_type": "AugAssign",
            "op": {"ast_type": "Add"},
            "target": {
                "attr": "counter",
                "value": {"id": "lib1", "ast_type": "Name"},
                "ast_type": "Attribute",
                "variable_reads": [
                    {
                        "name": "counter",
                        "decl_node": {"node_id": 19, "source_id": 1},
                        "access_path": [],
                    }
                ],
                "variable_writes": [
                    {
                        "name": "counter",
                        "decl_node": {"node_id": 19, "source_id": 1},
                        "access_path": [],
                    }
                ],
            },
        },
    ]

    assert bar["name"] == "bar"
    assert bar["body"] == [
        {
            "value": {
                "value": {"ast_type": "Name", "id": "lib1"},
                "attr": "counter",
                "ast_type": "Attribute",
                "variable_reads": [
                    {
                        "name": "counter",
                        "decl_node": {"node_id": 19, "source_id": 1},
                        "access_path": [],
                    }
                ],
            },
            "ast_type": "AnnAssign",
            "target": {
                "ast_type": "Name",
                "id": "x",
                "variable_reads": [
                    {"name": "x", "decl_node": {"node_id": 24, "source_id": 0}, "access_path": []}
                ],
            },
            "annotation": {"ast_type": "Name", "id": "uint256"},
        },
        {
            "value": {
                "value": {"ast_type": "Name", "id": "self"},
                "attr": "counter",
                "ast_type": "Attribute",
                "variable_reads": [
                    {
                        "name": "counter",
                        "decl_node": {"node_id": 6, "source_id": 0},
                        "access_path": [],
                    }
                ],
            },
            "ast_type": "AnnAssign",
            "target": {
                "ast_type": "Name",
                "id": "y",
                "variable_reads": [
                    {"name": "y", "decl_node": {"node_id": 29, "source_id": 0}, "access_path": []}
                ],
            },
            "annotation": {"ast_type": "Name", "id": "uint256"},
        },
        {
            "op": {"ast_type": "Add"},
            "value": {"value": 1, "ast_type": "Int"},
            "ast_type": "AugAssign",
            "target": {
                "value": {"ast_type": "Name", "id": "lib1"},
                "attr": "counter",
                "ast_type": "Attribute",
                "variable_reads": [
                    {
                        "name": "counter",
                        "decl_node": {"node_id": 19, "source_id": 1},
                        "access_path": [],
                    }
                ],
                "variable_writes": [
                    {
                        "name": "counter",
                        "decl_node": {"node_id": 19, "source_id": 1},
                        "access_path": [],
                    }
                ],
            },
        },
    ]

    assert baz["name"] == "baz"
    assert baz["body"] == [
        {
            "value": {
                "func": {
                    "attr": "bar",
                    "value": {"id": "self", "ast_type": "Name"},
                    "ast_type": "Attribute",
                    "variable_reads": [
                        {
                            "name": "counter",
                            "decl_node": {"node_id": 19, "source_id": 1},
                            "access_path": [],
                        },
                        {
                            "name": "counter",
                            "decl_node": {"node_id": 6, "source_id": 0},
                            "access_path": [],
                        },
                    ],
                    "variable_writes": [
                        {
                            "name": "counter",
                            "decl_node": {"node_id": 19, "source_id": 1},
                            "access_path": [],
                        }
                    ],
                },
                "args": [],
                "keywords": [],
                "ast_type": "Call",
            },
            "ast_type": "Expr",
        },
        {
            "op": {"ast_type": "Add"},
            "value": {"value": 1, "ast_type": "Int"},
            "ast_type": "AugAssign",
            "target": {
                "attr": "counter",
                "value": {"id": "self", "ast_type": "Name"},
                "ast_type": "Attribute",
                "variable_reads": [
                    {
                        "name": "counter",
                        "decl_node": {"node_id": 6, "source_id": 0},
                        "access_path": [],
                    }
                ],
                "variable_writes": [
                    {
                        "name": "counter",
                        "decl_node": {"node_id": 6, "source_id": 0},
                        "access_path": [],
                    }
                ],
            },
        },
    ]

    assert qux["name"] == "qux"
    assert qux["body"] == [
        {
            "ast_type": "Assign",
            "value": {"ast_type": "List", "elements": []},
            "target": {
                "ast_type": "Attribute",
                "attr": "bars",
                "value": {"ast_type": "Name", "id": "lib1"},
                "variable_reads": [
                    {
                        "name": "bars",
                        "decl_node": {"node_id": 22, "source_id": 1},
                        "access_path": [],
                    }
                ],
                "variable_writes": [
                    {
                        "name": "bars",
                        "decl_node": {"node_id": 22, "source_id": 1},
                        "access_path": [],
                    }
                ],
            },
        },
        {
            "ast_type": "Assign",
            "value": {
                "func": {"ast_type": "Name", "id": "empty"},
                "ast_type": "Call",
                "args": [
                    {
                        "ast_type": "Attribute",
                        "attr": "Bar",
                        "value": {"ast_type": "Name", "id": "lib1"},
                    }
                ],
                "keywords": [],
            },
            "target": {
                "slice": {"ast_type": "Int", "value": 0},
                "ast_type": "Subscript",
                "value": {
                    "ast_type": "Attribute",
                    "attr": "bars",
                    "value": {"ast_type": "Name", "id": "lib1"},
                    "variable_reads": [
                        {
                            "name": "bars",
                            "decl_node": {"node_id": 22, "source_id": 1},
                            "access_path": [],
                        }
                    ],
                },
                "variable_reads": [
                    {
                        "name": "bars",
                        "decl_node": {"node_id": 22, "source_id": 1},
                        "access_path": ["$subscript_access"],
                    }
                ],
                "variable_writes": [
                    {
                        "name": "bars",
                        "decl_node": {"node_id": 22, "source_id": 1},
                        "access_path": ["$subscript_access"],
                    }
                ],
            },
        },
        {
            "ast_type": "Assign",
            "value": {
                "func": {"ast_type": "Name", "id": "empty"},
                "ast_type": "Call",
                "args": [
                    {
                        "slice": {"ast_type": "Int", "value": 2},
                        "ast_type": "Subscript",
                        "value": {
                            "ast_type": "Attribute",
                            "attr": "Foo",
                            "value": {"ast_type": "Name", "id": "lib1"},
                        },
                    }
                ],
                "keywords": [],
            },
            "target": {
                "ast_type": "Attribute",
                "attr": "items",
                "value": {
                    "slice": {"ast_type": "Int", "value": 1},
                    "ast_type": "Subscript",
                    "value": {
                        "ast_type": "Attribute",
                        "attr": "bars",
                        "value": {"ast_type": "Name", "id": "lib1"},
                        "variable_reads": [
                            {
                                "name": "bars",
                                "decl_node": {"node_id": 22, "source_id": 1},
                                "access_path": [],
                            }
                        ],
                    },
                    "variable_reads": [
                        {
                            "name": "bars",
                            "decl_node": {"node_id": 22, "source_id": 1},
                            "access_path": ["$subscript_access"],
                        }
                    ],
                },
                "variable_reads": [
                    {
                        "name": "bars",
                        "decl_node": {"node_id": 22, "source_id": 1},
                        "access_path": ["$subscript_access", "items"],
                    }
                ],
                "variable_writes": [
                    {
                        "name": "bars",
                        "decl_node": {"node_id": 22, "source_id": 1},
                        "access_path": ["$subscript_access", "items"],
                    }
                ],
            },
        },
        {
            "ast_type": "Assign",
            "value": {"ast_type": "Int", "value": 1},
            "target": {
                "ast_type": "Attribute",
                "attr": "a",
                "value": {
                    "slice": {"ast_type": "Int", "value": 0},
                    "ast_type": "Subscript",
                    "value": {
                        "ast_type": "Attribute",
                        "attr": "items",
                        "value": {
                            "slice": {"ast_type": "Int", "value": 1},
                            "ast_type": "Subscript",
                            "value": {
                                "ast_type": "Attribute",
                                "attr": "bars",
                                "value": {"ast_type": "Name", "id": "lib1"},
                                "variable_reads": [
                                    {
                                        "name": "bars",
                                        "decl_node": {"node_id": 22, "source_id": 1},
                                        "access_path": [],
                                    }
                                ],
                            },
                            "variable_reads": [
                                {
                                    "name": "bars",
                                    "decl_node": {"node_id": 22, "source_id": 1},
                                    "access_path": ["$subscript_access"],
                                }
                            ],
                        },
                        "variable_reads": [
                            {
                                "name": "bars",
                                "decl_node": {"node_id": 22, "source_id": 1},
                                "access_path": ["$subscript_access", "items"],
                            }
                        ],
                    },
                    "variable_reads": [
                        {
                            "name": "bars",
                            "decl_node": {"node_id": 22, "source_id": 1},
                            "access_path": ["$subscript_access", "items", "$subscript_access"],
                        }
                    ],
                },
                "variable_reads": [
                    {
                        "name": "bars",
                        "decl_node": {"node_id": 22, "source_id": 1},
                        "access_path": ["$subscript_access", "items", "$subscript_access", "a"],
                    }
                ],
                "variable_writes": [
                    {
                        "name": "bars",
                        "decl_node": {"node_id": 22, "source_id": 1},
                        "access_path": ["$subscript_access", "items", "$subscript_access", "a"],
                    }
                ],
            },
        },
        {
            "ast_type": "Assign",
            "value": {"ast_type": "Decimal", "value": "10.0"},
            "target": {
                "ast_type": "Attribute",
                "attr": "c",
                "value": {
                    "slice": {"ast_type": "Int", "value": 1},
                    "ast_type": "Subscript",
                    "value": {
                        "ast_type": "Attribute",
                        "attr": "items",
                        "value": {
                            "slice": {"ast_type": "Int", "value": 0},
                            "ast_type": "Subscript",
                            "value": {
                                "ast_type": "Attribute",
                                "attr": "bars",
                                "value": {"ast_type": "Name", "id": "lib1"},
                                "variable_reads": [
                                    {
                                        "name": "bars",
                                        "decl_node": {"node_id": 22, "source_id": 1},
                                        "access_path": [],
                                    }
                                ],
                            },
                            "variable_reads": [
                                {
                                    "name": "bars",
                                    "decl_node": {"node_id": 22, "source_id": 1},
                                    "access_path": ["$subscript_access"],
                                }
                            ],
                        },
                        "variable_reads": [
                            {
                                "name": "bars",
                                "decl_node": {"node_id": 22, "source_id": 1},
                                "access_path": ["$subscript_access", "items"],
                            }
                        ],
                    },
                    "variable_reads": [
                        {
                            "name": "bars",
                            "decl_node": {"node_id": 22, "source_id": 1},
                            "access_path": ["$subscript_access", "items", "$subscript_access"],
                        }
                    ],
                },
                "variable_reads": [
                    {
                        "name": "bars",
                        "decl_node": {"node_id": 22, "source_id": 1},
                        "access_path": ["$subscript_access", "items", "$subscript_access", "c"],
                    }
                ],
                "variable_writes": [
                    {
                        "name": "bars",
                        "decl_node": {"node_id": 22, "source_id": 1},
                        "access_path": ["$subscript_access", "items", "$subscript_access", "c"],
                    }
                ],
            },
        },
    ]

    assert qux2["name"] == "qux2"
    assert qux2["body"] == [
        {
            "value": {
                "args": [],
                "func": {
                    "value": {"ast_type": "Name", "id": "self"},
                    "attr": "qux",
                    "ast_type": "Attribute",
                    "variable_reads": [
                        {
                            "name": "bars",
                            "decl_node": {"node_id": 22, "source_id": 1},
                            "access_path": [],
                        },
                        {
                            "name": "bars",
                            "decl_node": {"node_id": 22, "source_id": 1},
                            "access_path": ["$subscript_access"],
                        },
                        {
                            "name": "bars",
                            "decl_node": {"node_id": 22, "source_id": 1},
                            "access_path": ["$subscript_access", "items"],
                        },
                        {
                            "name": "bars",
                            "decl_node": {"node_id": 22, "source_id": 1},
                            "access_path": ["$subscript_access", "items", "$subscript_access"],
                        },
                        {
                            "name": "bars",
                            "decl_node": {"node_id": 22, "source_id": 1},
                            "access_path": ["$subscript_access", "items", "$subscript_access", "a"],
                        },
                        {
                            "name": "bars",
                            "decl_node": {"node_id": 22, "source_id": 1},
                            "access_path": ["$subscript_access", "items", "$subscript_access", "c"],
                        },
                    ],
                    "variable_writes": [
                        {
                            "name": "bars",
                            "decl_node": {"node_id": 22, "source_id": 1},
                            "access_path": [],
                        },
                        {
                            "name": "bars",
                            "decl_node": {"node_id": 22, "source_id": 1},
                            "access_path": ["$subscript_access"],
                        },
                        {
                            "name": "bars",
                            "decl_node": {"node_id": 22, "source_id": 1},
                            "access_path": ["$subscript_access", "items"],
                        },
                        {
                            "name": "bars",
                            "decl_node": {"node_id": 22, "source_id": 1},
                            "access_path": ["$subscript_access", "items", "$subscript_access", "a"],
                        },
                        {
                            "name": "bars",
                            "decl_node": {"node_id": 22, "source_id": 1},
                            "access_path": ["$subscript_access", "items", "$subscript_access", "c"],
                        },
                    ],
                },
                "ast_type": "Call",
                "keywords": [],
            },
            "ast_type": "Expr",
        }
    ]


def test_annotated_ast_export_recursion(make_input_bundle):
    sources = {
        "main.vy": """
import lib1

@external
def foo():
    lib1.foo()
    """,
        "lib1.vy": """
import lib2

def foo():
    lib2.foo()
    """,
        "lib2.vy": """
def foo():
    pass
    """,
    }

    input_bundle = make_input_bundle(sources)

    def compile_and_get_ast(file_name):
        file = input_bundle.load_file(file_name)
        output = compiler.compile_from_file_input(
            file, input_bundle=input_bundle, output_formats=["annotated_ast_dict"]
        )
        return output["annotated_ast_dict"]

    lib1_ast = compile_and_get_ast("lib1.vy")["ast"]
    lib2_ast = compile_and_get_ast("lib2.vy")["ast"]
    main_out = compile_and_get_ast("main.vy")

    lib1_import_ast = main_out["imports"][1]
    lib2_import_ast = main_out["imports"][0]

    # path is once virtual, once libX.vy
    # type contains name which is based on path
    keys = [s for s in lib1_import_ast.keys() if s not in {"path", "type"}]

    for key in keys:
        assert lib1_ast[key] == lib1_import_ast[key]
        assert lib2_ast[key] == lib2_import_ast[key]

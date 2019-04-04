from vyper import (
    compiler,
)
from vyper.ast_utils import (
    ast_to_dict,
    dict_to_ast,
    parse_to_ast,
)


def get_node_ids(ast_struct, ids=None):
    if ids is None:
        ids = []

    for k, v in ast_struct.items():
        print(k, v, ids)
        if isinstance(v, dict):
            ids = get_node_ids(v, ids)
        elif isinstance(v, list):
            for x in v:
                ids = get_node_ids(x, ids)
        elif k == 'node_id':
            ids.append(v)
    return ids


def test_ast_to_dict_node_id():
    code = """
@public
def test() -> int128:
    a: uint256 = 100
    return 123
    """
    dict_out = compiler.compile_code(code, ['ast_dict'])
    node_ids = get_node_ids(dict_out)

    assert len(node_ids) == len(set(node_ids))


def test_basic_ast():
    code = """
a: int128
    """
    dict_out = compiler.compile_code(code, ['ast_dict'])
    assert dict_out['ast_dict']['ast'][0] == {
      'annotation': {
        'ast_type': 'Name',
        'col_offset': 3,
        'id': 'int128',
        'lineno': 2,
        'node_id': 4
      },
      'ast_type': 'AnnAssign',
      'col_offset': 0,
      'lineno': 2,
      'node_id': 1,
      'simple': 1,
      'target': {
        'ast_type': 'Name',
        'col_offset': 0,
        'id': 'a',
        'lineno': 2,
        'node_id': 2
      },
      'value': None
    }


def test_dict_to_ast():
    code = """
@public
def test() -> int128:
    a: uint256 = 100
    return 123
    """

    original_ast = parse_to_ast(code)
    out_dict = ast_to_dict(original_ast)
    new_ast = dict_to_ast(out_dict)

    assert new_ast == original_ast

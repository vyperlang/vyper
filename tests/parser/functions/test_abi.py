from vyper.compiler import (
    compile_code,
    mk_full_signature,
)


def test_only_init_function():
    code = """
x: int128

@public
def __init__():
    self.x = 1
    """
    code_init_empty = """
x: int128

@public
def __init__():
    pass
    """

    empty_sig = [{
        'outputs': [],
        'inputs': [],
        'constant': False,
        'payable': False,
        'type': 'constructor'
    }]

    assert mk_full_signature(code) == empty_sig
    assert mk_full_signature(code_init_empty) == empty_sig


def test_default_abi():
    default_code = """
@payable
@public
def __default__():
    pass
    """

    assert mk_full_signature(default_code) == [{
        'constant': False,
        'payable': True,
        'type': 'fallback'
    }]


def test_method_identifiers():
    code = """
x: public(int128)

@public
def foo(x: uint256) -> bytes[100]:
    return b"hello"
    """

    out = compile_code(
        code,
        output_formats=['method_identifiers'],
    )

    assert out['method_identifiers'] == {
        'foo(uint256)': '0x2fbebd38',
        'x()': '0xc55699c'
    }


def test_struct_abi():
    code = """
struct MyStruct:
    a: address
    b: uint256

@public
@constant
def foo(s: MyStruct) -> MyStruct:
    return s
    """

    abi = mk_full_signature(code)
    func_abi = abi[0]

    assert func_abi["name"] == "foo"
    expected = {
        'type': 'tuple',
        'name': '',
        'components': [
           {'type': 'address', 'name': 'a'},
           {'type': 'uint256', 'name': 'b'}
        ]
    }

    assert func_abi["outputs"][0] == expected

    expected['name'] = "s"
    assert func_abi["inputs"][0] == expected

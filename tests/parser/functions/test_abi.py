from vyper.compiler import (
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

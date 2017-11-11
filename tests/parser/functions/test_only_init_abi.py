from viper.compiler import mk_full_signature


def test_only_init_function():
    code = """
x: num

@public
def __init__():
    self.x = 1
    """
    code_init_empty = """
x: num

@public
def __init__():
    pass
    """

    empty_sig = [{
        'name': '__init__',
        'outputs': [],
        'inputs': [],
        'constant': False,
        'payable': False,
        'type': 'constructor'
    }]

    assert mk_full_signature(code) == empty_sig
    assert mk_full_signature(code_init_empty) == empty_sig

from viper.compiler import mk_full_signature


def test_only_init_function():
    code = """
x: num

def __init__():
    self.x = 1
    """

    assert mk_full_signature(code) == [{
        'name': '__init__',
        'outputs': [],
        'inputs': [],
        'constant': False,
        'payable': False,
        'type': 'constructor'
    }]

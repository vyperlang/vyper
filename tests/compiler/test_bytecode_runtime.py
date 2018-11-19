from vyper import compiler


def test_bytecode_runtime():
    code = """
@public
def a() -> bool:
    return True
    """

    out = compiler.compile({'': code}, ['bytecode_runtime', 'bytecode'], output_type='list')[0]

    assert len(out['bytecode']) > len(out['bytecode_runtime'])
    assert out['bytecode_runtime'][2:] in out['bytecode'][2:]

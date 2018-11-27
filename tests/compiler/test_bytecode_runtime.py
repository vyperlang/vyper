import vyper


def test_bytecode_runtime():
    code = """
@public
def a() -> bool:
    return True
    """

    out = vyper.compile_codes({'': code}, ['bytecode_runtime', 'bytecode'])[0]

    assert len(out['bytecode']) > len(out['bytecode_runtime'])
    assert out['bytecode_runtime'][2:] in out['bytecode'][2:]

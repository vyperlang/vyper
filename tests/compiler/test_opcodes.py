import vyper


def test_opcodes():
    code = """
@public
def a() -> bool:
    return True
    """

    out = vyper.compile_codes({'': code}, ['opcodes_runtime', 'opcodes'])[0]

    assert len(out['opcodes']) > len(out['opcodes_runtime'])
    assert out['opcodes_runtime'] in out['opcodes']

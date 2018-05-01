from vyper import compiler


def test_bytecode_runtime():
    code = """
@public
def a() -> bool:
    return True
    """

    bytecode = compiler.compile(code)
    bytecode_runtime = compiler.compile(code, bytecode_runtime=True)

    assert len(bytecode) > len(bytecode_runtime)
    assert bytecode_runtime in bytecode

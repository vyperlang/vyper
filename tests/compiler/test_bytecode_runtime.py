import vyper


def test_bytecode_runtime():
    code = """
@external
def a() -> bool:
    return True
    """

    out = vyper.compile_code(code, ["bytecode_runtime", "bytecode"])

    assert len(out["bytecode"]) > len(out["bytecode_runtime"])
    assert out["bytecode_runtime"][2:] in out["bytecode"][2:]

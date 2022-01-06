from vyper.compiler import compile_code


def test_storage_layout_overrides():
    code = """
a: uint256
b: uint256"""

    storage_layout_overrides = {
        "a": {"type": "uint256", "location": "storage", "slot": 1},
        "b": {"type": "uint256", "location": "storage", "slot": 0},
    }

    out = compile_code(
        code, output_formats=["layout"], storage_layout_override=storage_layout_overrides
    )

    assert out["layout"] == {
        "a": {"type": "uint256", "location": "storage", "slot": 1},
        "b": {"type": "uint256", "location": "storage", "slot": 0},
    }

from vyper.compiler import compile_code
from vyper.compiler.output import _compress_source_map
from vyper.compiler.utils import expand_source_map

TEST_CODE = """
@internal
def _baz(a: int128) -> int128:
    b: int128 = a
    for i in range(2, 5):
        b *=  i
        if b > 31337:
            break
    return b

@internal
def _bar(a: uint256) -> bool:
    if a > 42:
        return True
    return False

@external
def foo(a: uint256) -> int128:
    if self._bar(a):
        return self._baz(2)
    else:
        return 42
    """


def test_jump_map():
    source_map = compile_code(TEST_CODE, ["source_map"])["source_map"]
    pos_map = source_map["pc_pos_map"]
    jump_map = source_map["pc_jump_map"]

    assert len([v for v in jump_map.values() if v == "o"]) == 3
    assert len([v for v in jump_map.values() if v == "i"]) == 2

    code_lines = [i + "\n" for i in TEST_CODE.split("\n")]
    for pc in [k for k, v in jump_map.items() if v == "o"]:
        lineno, col_offset, _, end_col_offset = pos_map[pc]
        assert code_lines[lineno - 1][col_offset:end_col_offset].startswith("return")

    for pc in [k for k, v in jump_map.items() if v == "i"]:
        lineno, col_offset, _, end_col_offset = pos_map[pc]
        assert code_lines[lineno - 1][col_offset:end_col_offset].startswith("self.")


def test_pos_map_offsets():
    source_map = compile_code(TEST_CODE, ["source_map"])["source_map"]
    expanded = expand_source_map(source_map["pc_pos_map_compressed"])

    pc_iter = iter(source_map["pc_pos_map"][i] for i in sorted(source_map["pc_pos_map"]))
    jump_iter = iter(source_map["pc_jump_map"][i] for i in sorted(source_map["pc_jump_map"]))
    code_lines = [i + "\n" for i in TEST_CODE.split("\n")]

    for item in expanded:
        if item[-1] is not None:
            assert next(jump_iter) == item[-1]

        if item[:2] != [-1, -1]:
            start, length = item[:2]
            lineno, col_offset, end_lineno, end_col_offset = next(pc_iter)
            assert code_lines[lineno - 1][col_offset] == TEST_CODE[start]
            assert length == (
                sum(len(i) for i in code_lines[lineno - 1 : end_lineno])  # noqa: E203
                - col_offset
                - (len(code_lines[end_lineno - 1]) - end_col_offset)
            )


def test_compress_source_map():
    code = """
@external
def foo() -> uint256:
    return 42
    """
    compressed = _compress_source_map(
        code, {"0": None, "2": (2, 0, 4, 13), "3": (2, 0, 2, 8), "5": (2, 0, 2, 8)}, {"3": "o"}, 2
    )
    assert compressed == "-1:-1:2:-;1:45;:8::o;;"


def test_expand_source_map():
    compressed = "-1:-1:0:-;;13:42:1;:21;::0:o;:::-;1::1;"
    expanded = [
        [-1, -1, 0, "-"],
        [-1, -1, 0, None],
        [13, 42, 1, None],
        [13, 21, 1, None],
        [13, 21, 0, "o"],
        [13, 21, 0, "-"],
        [1, 21, 1, None],
    ]
    assert expand_source_map(compressed) == expanded

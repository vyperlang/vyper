import os
import subprocess
import sys

# the pointers of the `Bytes` locals escape into `self._f`, and each
# if/else arm gives its local the same live range. the memory allocator
# must resolve such ties by program order, not by object-identity hash
# order, which differs between processes.
CONTRACT = """
@internal
def _f(a: Bytes[64]) -> uint256:
    s: uint256 = 0
    for i: uint256 in range(len(a), bound=64):
        s += convert(slice(a, i, 1), uint256)
    return s

@external
def foo(x: Bytes[64], y: Bytes[64], flags: bool[4]) -> uint256:
    n: uint256 = 0
    if flags[0]:
        a0: Bytes[64] = x
        n += self._f(a0)
    else:
        b0: Bytes[64] = y
        n += self._f(b0)
    if flags[1]:
        a1: Bytes[64] = x
        n += self._f(a1)
    else:
        b1: Bytes[64] = y
        n += self._f(b1)
    if flags[2]:
        a2: Bytes[64] = x
        n += self._f(a2)
    else:
        b2: Bytes[64] = y
        n += self._f(b2)
    if flags[3]:
        a3: Bytes[64] = x
        n += self._f(a3)
    else:
        b3: Bytes[64] = y
        n += self._f(b3)
    return n
"""


def test_memory_allocation_stability(tmp_path):
    # object-identity hashes are not fixed by PYTHONHASHSEED, so the
    # bytecode must be compared across fresh compiler processes. varying
    # the seed changes allocation patterns and thereby object addresses.
    path = tmp_path / "foo.vy"
    path.write_text(CONTRACT)

    outputs = set()
    for seed in range(8):
        env = {**os.environ, "PYTHONHASHSEED": str(seed)}
        cmd = [sys.executable, "-m", "vyper", "--experimental-codegen", "-f", "bytecode_runtime"]
        res = subprocess.run(cmd + [str(path)], env=env, capture_output=True, text=True, check=True)
        outputs.add(res.stdout.strip())

    assert len(outputs) == 1, f"{len(outputs)} distinct outputs across processes"

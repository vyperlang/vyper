from collections import namedtuple

from vyper.compiler import compile_code
from vyper.compiler.output import _compress_source_map
from vyper.compiler.settings import Settings
from vyper.compiler.utils import expand_source_map

TEST_CODE = """
@internal
def foo(a: uint256) -> uint256:
    return a + 1

# force foo to not be inlined
@external
def bar(a: uint256) -> uint256:
    return self.foo(a)

@external
def baz(a: uint256) -> uint256:
    return self.foo(a + 1)
"""

def test_simple_map():
    code = TEST_CODE
    output = compile_code(code, output_formats=["symbol_map_runtime", "metadata"], settings=Settings(experimental_codegen=True))
    meta = output["metadata"]
    symbol_map = output["symbol_map_runtime"]
    foo_meta_ent = None
    assert "function_info" in meta, "missing function info in metadata"
    function_infos = meta["function_info"]
    assert isinstance(function_infos, dict), "function info is not a dict"
    for (k, v) in function_infos.items():
        if v["name"] == "foo" and v["visibility"] == "internal":
            foo_meta_ent = v
            break
    assert foo_meta_ent is not None, "didn't find entry for foo"
    assert "venom_via_stack" in foo_meta_ent, "no stack info"
    assert foo_meta_ent.get("venom_return_via_stack", False), "unexpected non-stack return"
    assert foo_meta_ent["venom_via_stack"] == ["a"]
    foo_id = foo_meta_ent["_ir_identifier"]
    symbol_map_key = "_sym_" + foo_id + "_runtime"
    assert symbol_map_key in symbol_map, "missing constant start for foo()"

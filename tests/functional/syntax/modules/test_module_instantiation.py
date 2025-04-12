import pytest

from vyper.compiler import compile_code
from vyper.exceptions import InstantiationException, StructureException

fail_list = [
    (
        """
import lib1
h: HashMap[uint256, lib1]
""",
        InstantiationException,
        ".*is not instantiable in storage",
    ),
    (
        """
import lib1

struct S:
    l: lib1
    """,
        StructureException,
        ".*not a valid struct member",
    ),
    (
        """
import lib1

d: DynArray[lib1, 10]
    """,
        StructureException,
        ".*Arrays of.*are not allowed",
    ),
]


@pytest.mark.parametrize("bad_code,exc,match_regex", fail_list)
def test_module_instantiation(make_input_bundle, bad_code, exc, match_regex):
    lib1 = """
foo: uint256
        """

    input_bundle = make_input_bundle({"lib1.vy": lib1})

    with pytest.raises(exc, match=match_regex):
        compile_code(bad_code, input_bundle=input_bundle)

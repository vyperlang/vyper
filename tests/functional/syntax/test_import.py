import pytest

from vyper import compiler
from vyper.exceptions import ModuleNotFound


def test_implicitly_relative_import_crashes(make_input_bundle):
    top = """
import subdir0.lib0 as lib0

@external
def foo():
    lib0.foo()
    """

    lib0 = """
import subdir1.lib1 as lib1

def foo():
    lib1.foo()
    """

    lib1 = """

def foo():
    pass
    """

    input_bundle = make_input_bundle(
        {"top.vy": top, "subdir0/lib0.vy": lib0, "subdir0/subdir1/lib1.vy": lib1}
    )

    with pytest.raises(ModuleNotFound):
        compiler.compile_code(top, input_bundle=input_bundle)

    lib0 = """
from subdir1 import lib1 as lib1

def foo():
    lib1.foo()
    """

    input_bundle = make_input_bundle(
        {"top.vy": top, "subdir0/lib0.vy": lib0, "subdir0/subdir1/lib1.vy": lib1}
    )

    with pytest.raises(ModuleNotFound):
        compiler.compile_code(top, input_bundle=input_bundle)


def test_absolute_path_passes(make_input_bundle):
    top = """
import subdir0.lib0 as lib0

@external
def foo():
    lib0.foo()
    """

    lib0 = """
import subdir0.subdir1.lib1 as lib1

def foo():
    lib1.foo()
    """

    lib1 = """

def foo():
    pass
    """

    input_bundle = make_input_bundle(
        {"top.vy": top, "subdir0/lib0.vy": lib0, "subdir0/subdir1/lib1.vy": lib1}
    )
    compiler.compile_code(top, input_bundle=input_bundle)

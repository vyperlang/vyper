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

    file_input = input_bundle.load_file("top.vy")
    with pytest.raises(ModuleNotFound):
        compiler.compile_from_file_input(file_input, input_bundle=input_bundle)

    lib0 = """
from subdir1 import lib1 as lib1
def foo():
    lib1.foo()
    """

    input_bundle = make_input_bundle(
        {"top.vy": top, "subdir0/lib0.vy": lib0, "subdir0/subdir1/lib1.vy": lib1}
    )

    file_input = input_bundle.load_file("top.vy")
    with pytest.raises(ModuleNotFound):
        compiler.compile_from_file_input(file_input, input_bundle=input_bundle)


def test_relative_import_searches_only_current_path(make_input_bundle):
    top = """
from subdir import b as b
@external
def foo():
    b.foo()
    """

    a = """
def foo():
    pass
    """

    b = """
from . import a as a
def foo():
    a.foo()
    """

    input_bundle = make_input_bundle({"top.vy": top, "a.vy": a, "subdir/b.vy": b})

    with pytest.raises(ModuleNotFound):
        compiler.compile_code(top, input_bundle=input_bundle)


def test_absolute_import_within_relative_import(make_input_bundle):
    top = """
import subdir0.subdir1.c as c
@external
def foo():
    c.foo()
        """
    a = """
import subdir0.b as b
def foo():
    b.foo()
            """
    b = """
def foo():
    pass
        """

    c = """
from .. import a as a
def foo():
    a.foo()
        """

    input_bundle = make_input_bundle(
        {"top.vy": top, "subdir0/a.vy": a, "subdir0/b.vy": b, "subdir0/subdir1/c.vy": c}
    )
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

    lib0 = """
from .subdir1 import lib1 as lib1
def foo():
    lib1.foo()
    """

    input_bundle = make_input_bundle(
        {"top.vy": top, "subdir0/lib0.vy": lib0, "subdir0/subdir1/lib1.vy": lib1}
    )
    compiler.compile_code(top, input_bundle=input_bundle)

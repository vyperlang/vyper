import pytest

from vyper.compiler import compile_code
from vyper.exceptions import StructureException


def test_implements_from_vyi(make_input_bundle):
    vyi = """
@external
def foo():
    ...
    """
    lib1 = """
import some_interface
    """
    main = """
import lib1

implements: lib1.some_interface

@external
def foo():  # implementation
    pass
    """
    input_bundle = make_input_bundle({"some_interface.vyi": vyi, "lib1.vy": lib1})

    assert compile_code(main, input_bundle=input_bundle) is not None


def test_implements_from_vyi2(make_input_bundle):
    # test implements via nested imported vyi file
    vyi = """
@external
def foo():
    ...
    """
    lib1 = """
import some_interface
    """
    lib2 = """
import lib1
    """
    main = """
import lib2

implements: lib2.lib1.some_interface

@external
def foo():  # implementation
    pass
    """
    input_bundle = make_input_bundle({"some_interface.vyi": vyi, "lib1.vy": lib1, "lib2.vy": lib2})

    assert compile_code(main, input_bundle=input_bundle) is not None


def test_implements_empty_vyi(make_input_bundle, tmp_path):
    vyi = ""
    input_bundle = make_input_bundle({"some_interface.vyi": vyi})
    main = """
import some_interface

implements: some_interface
    """
    with pytest.raises(StructureException) as e:
        _ = compile_code(main, input_bundle=input_bundle)

    vyi_path = (tmp_path / "some_interface.vyi").as_posix()
    assert (
        e.value._message
        == f"Tried to implement `{vyi_path}`, but it has no functions to implement!"
    )

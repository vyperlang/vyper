from vyper.compiler import compile_code


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

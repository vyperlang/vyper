import pytest

from vyper.compiler import compile_code
from vyper.exceptions import CallViolation, UnknownAttribute


def test_call_deploy_from_external(make_input_bundle):
    lib1 = """
@deploy
def __init__():
    pass
    """

    main = """
import lib1

@external
def foo():
    lib1.__init__()
    """

    input_bundle = make_input_bundle({"lib1.vy": lib1})

    with pytest.raises(CallViolation) as e:
        compile_code(main, input_bundle=input_bundle)

    assert e.value.message == "Cannot call an @deploy function from an @external function!"


@pytest.mark.parametrize("interface_syntax", ["__interface__", "__at__"])
def test_module_interface_init(make_input_bundle, tmp_path, interface_syntax):
    lib1 = """
#lib1.vy
k: uint256

@external
def bar():
    pass

@deploy
def __init__():
    self.k = 10
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1})

    code = f"""
import lib1

@deploy
def __init__():
    lib1.{interface_syntax}(self).__init__()
    """

    with pytest.raises(UnknownAttribute) as e:
        compile_code(code, input_bundle=input_bundle)

    # as_posix() for windows tests
    lib1_path = (tmp_path / "lib1.vy").as_posix()
    assert e.value.message == f"interface {lib1_path} has no member '__init__'."

import pytest

from vyper.compiler import compile_code
from vyper.exceptions import CallViolation


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

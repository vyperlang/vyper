def test_module_constant(make_input_bundle, get_contract):
    mod1 = """
X: constant(uint256) = 12345
    """
    contract = """
import mod1

@external
def foo() -> uint256:
    return mod1.X
    """

    input_bundle = make_input_bundle({"mod1.vy": mod1})

    c = get_contract(contract, input_bundle=input_bundle)

    assert c.foo() == 12345


def test_nested_module_constant(make_input_bundle, get_contract):
    # test nested module constants
    # test at least 3 modules deep to test the `path.reverse()` gizmo
    # in ConstantFolder.visit_Attribute()
    mod1 = """
X: constant(uint256) = 12345
    """
    mod2 = """
import mod1
X: constant(uint256) = 54321
    """
    mod3 = """
import mod2
X: constant(uint256) = 98765
    """

    contract = """
import mod1
import mod2
import mod3

@external
def test_foo() -> bool:
    assert mod1.X == 12345
    assert mod2.X == 54321
    assert mod3.X == 98765
    assert mod2.mod1.X == mod1.X
    assert mod3.mod2.mod1.X == mod1.X
    assert mod3.mod2.X == mod2.X
    return True
    """

    input_bundle = make_input_bundle({"mod1.vy": mod1, "mod2.vy": mod2, "mod3.vy": mod3})

    c = get_contract(contract, input_bundle=input_bundle)
    assert c.test_foo() is True


def test_import_constant_array(make_input_bundle, get_contract, tx_failed):
    mod1 = """
X: constant(uint256[3]) = [1,2,3]
    """
    contract = """
import mod1

@external
def foo(ix: uint256) -> uint256:
    return mod1.X[ix]
    """

    input_bundle = make_input_bundle({"mod1.vy": mod1})

    c = get_contract(contract, input_bundle=input_bundle)

    assert c.foo(0) == 1
    assert c.foo(1) == 2
    assert c.foo(2) == 3
    with tx_failed():
        c.foo(3)


def test_module_constant_builtin(make_input_bundle, get_contract):
    # test empty builtin, which is not (currently) foldable 2024-02-06
    mod1 = """
X: constant(uint256) = empty(uint256)
    """
    contract = """
import mod1

@external
def foo() -> uint256:
    return mod1.X
    """

    input_bundle = make_input_bundle({"mod1.vy": mod1})

    c = get_contract(contract, input_bundle=input_bundle)

    assert c.foo() == 0

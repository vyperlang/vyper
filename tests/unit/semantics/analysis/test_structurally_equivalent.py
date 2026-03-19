from vyper.ast import parse_to_ast
from vyper.ast.nodes import Attribute
from vyper.compiler.phases import CompilerData
from vyper.semantics.analysis import analyze_modules
from vyper.semantics.analysis.utils import structurally_equivalent
from vyper.utils import OrderedSet


def test_self_foo_different_modules_not_equal():
    """
    self.FOO from two different modules should not be semantically equal,
    even though they have the same textual representation.
    """
    module1_code = """
FOO: uint256

@internal
def bar() -> uint256:
    return self.FOO
    """

    module2_code = """
FOO: uint256

@internal
def bar() -> uint256:
    return self.FOO
    """

    def extract_self_foo(module_code):
        module = parse_to_ast(module1_code)
        analyze_modules(OrderedSet([module]))
        (self_foo,) = module.get_descendants(Attribute, {"attr": "FOO"})
        return self_foo

    self_foo_1 = extract_self_foo(module1_code)
    self_foo_2 = extract_self_foo(module2_code)

    # Even though textually identical, they should NOT be semantically equal
    # because they refer to different storage variables in different modules
    assert not structurally_equivalent(self_foo_1, self_foo_2)


def test_self_foo_equals_imported_module_foo(make_input_bundle):
    """
    self.FOO in a library module should be semantically equal to lib.FOO
    in a module that imports the library, since they refer to the same
    storage variable.
    """
    lib_code = """
FOO: uint256

@internal
def bar() -> uint256:
    return self.FOO
    """

    main_code = """
import lib

uses: lib

@internal
def baz() -> uint256:
    return lib.FOO
    """

    input_bundle = make_input_bundle({"lib.vy": lib_code})
    compiler_data = CompilerData(main_code, input_bundle=input_bundle)

    # Trigger analysis by accessing annotated_vyper_module
    main_module = compiler_data.annotated_vyper_module

    # Get the lib module via imported_modules dict
    lib_module = main_module._metadata["type"].imported_modules["lib"].module_node

    # Extract self.FOO from lib module
    lib_attrs = lib_module.get_descendants(Attribute, {"attr": "FOO"})
    assert len(lib_attrs) == 1
    self_foo = lib_attrs[0]

    # Extract lib.FOO from main module
    main_attrs = main_module.get_descendants(Attribute, {"attr": "FOO"})
    assert len(main_attrs) == 1
    lib_foo = main_attrs[0]

    # They should be semantically equal since lib.FOO refers to the same
    # storage variable as self.FOO in the lib module
    assert structurally_equivalent(self_foo, lib_foo)

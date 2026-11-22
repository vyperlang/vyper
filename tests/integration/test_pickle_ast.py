import copy
import pickle

from vyper.compiler.phases import CompilerData


def test_pickle_ast():
    code = """
import math

@external
def foo():
    self.bar()
    y: uint256 = 5
    x: uint256 = 5
def bar():
    pass
    """
    f = CompilerData(code)
    copy.deepcopy(f.annotated_vyper_module)
    pickle.loads(pickle.dumps(f.annotated_vyper_module))


def test_pickle_module_info_cycle(make_input_bundle):
    # `ModuleInfo.decl_node` closes a reference cycle through the AST back
    # to a set holding the same `ModuleInfo`, which must survive a pickle
    # roundtrip
    lib = """
x: uint256

@internal
@view
def _get() -> uint256:
    return self.x
    """
    mid = """
import lib

uses: lib

@external
@view
def first() -> uint256:
    return lib._get()

@external
@view
def second() -> uint256:
    return lib.x
    """
    main = """
import lib
import mid

initializes: lib
initializes: mid[lib := lib]
exports: (mid.first, mid.second)
    """
    input_bundle = make_input_bundle({"lib.vy": lib, "mid.vy": mid})
    f = CompilerData(main, input_bundle=input_bundle)
    bytecode = f.bytecode

    assert pickle.loads(pickle.dumps(f)).bytecode == bytecode

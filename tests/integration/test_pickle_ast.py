import copy
import pickle

from vyper.compiler.phases import CompilerData


def test_pickle_ast():
    code = """
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

from vyper import (
    compile_lll,
)
from vyper.optimization import (
    optimize_lll,
)
from vyper.parser.parser_utils import (
    LLLnode,
)


def test_sha3_32():
    lll = ['sha3_32', 0]
    evm = ['PUSH1', 0, 'PUSH1', 192, 'MSTORE', 'PUSH1', 32, 'PUSH1', 192, 'SHA3']
    assert compile_lll.compile_to_assembly(LLLnode.from_list(lll)) == evm
    assert compile_lll.compile_to_assembly(optimize_lll(LLLnode.from_list(lll))) == evm

import pytest

from vyper.parser.parser import LLLnode


fail_list = [
    [-2**255 - 3],
    [2**256 + 3],
    ['set', '_poz'],
    [['set', 'var_1', 0, 0]],
    ['with', 'var_1', 0, ['set', 1, 1]],
    ['break'],  # invalid break
    ['continue'],  # invalid continue
    ['invalidllelement']
]


@pytest.mark.parametrize('bad_lll', fail_list)
def test_lll_compile_fail(bad_lll, get_contract_from_lll, assert_compile_failed):
    assert_compile_failed(
        lambda: get_contract_from_lll(LLLnode.from_list(bad_lll)),
        Exception
    )


valid_list = [
    ['pass'],
    ['clamplt', ['mload', 0], 300],
    ['clampgt', ['mload', 0], -1],
    ['uclampgt', 1, ['mload', 0]],
    ['uclampge', ['mload', 0], 0],
]


@pytest.mark.parametrize('good_lll', valid_list)
def test_compile_lll_good(good_lll, get_contract_from_lll):
    get_contract_from_lll(LLLnode.from_list(good_lll))

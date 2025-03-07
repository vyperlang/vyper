import pytest

import vyper
from tests.venom_utils import PrePostChecker
from vyper.venom.passes import AlgebraicOptimizationPass, RemoveUnusedVariablesPass

pytestmark = pytest.mark.hevm

_check_pre_post = PrePostChecker(AlgebraicOptimizationPass, RemoveUnusedVariablesPass)


@pytest.mark.parametrize("iszero_count", range(5))
def test_simple_jump_case(iszero_count):
    """
    Test remove iszero chains to jnz
    """

    iszero_chain = ""
    for i in range(iszero_count):
        new = i + 1
        iszero_chain += f"""
        %cond{new} = iszero %cond{i}"""

    pre = f"""
    main:
        %par = param
        %1 = %par
        %2 = 64
        %3 = add %1, %2
        %cond0 = %3
        {iszero_chain}
        jnz %cond{iszero_count}, @then, @else
    then:
        %4 = add 10, %3
        sink %4
    else:
        %5 = add %3, %par
        sink %5
    """

    post_chain = "%cond1 = iszero %cond0" if iszero_count % 2 == 1 else ""

    post = f"""
    main:
        %par = param
        %1 = %par
        %2 = 64
        %3 = add %1, %2
        %cond0 = %3
        {post_chain}
        jnz %cond{iszero_count % 2}, @then, @else
    then:
        %4 = add 10, %3
        sink %4
    else:
        %5 = add %3, %par
        sink %5
    """

    _check_pre_post(pre, post)


@pytest.mark.parametrize("iszero_count", range(1, 5))
def test_simple_bool_cast_case(iszero_count):
    """
    Test that iszero chain elimination would not eliminate
    bool cast

    sink(izero(iszero(iszero(iszero(x))))) => sink(iszero(iszero(x)))

    You cannot remove all iszeros because the sink expects the bool
    and the total elimination would invalidate it
    """

    iszero_chain = ""
    for i in range(iszero_count):
        new = i + 1
        iszero_chain += f"""
        %cond{new} = iszero %cond{i}"""

    pre = f"""
    main:
        %par = param
        %1 = %par
        %2 = 64
        %3 = add %1, %2
        %cond0 = %3
        {iszero_chain}
        sink %cond{iszero_count}
    """

    if iszero_count % 2 == 0:
        post_chain = """
        %cond1 = iszero %cond0
        %cond2 = iszero %cond1
        """
        end_cond = "cond2"
    else:
        post_chain = """
        %cond1 = iszero %cond0
        """
        end_cond = "cond1"

    post = f"""
    main:
        %par = param
        %1 = %par
        %2 = 64
        %3 = add %1, %2
        %cond0 = %3
        {post_chain}
        sink %{end_cond}
    """

    _check_pre_post(pre, post)


@pytest.mark.parametrize("interleave_point", range(5))
def test_interleaved_case(interleave_point):
    """
    Test for the case where one of the iszeros results in
    the chain is used by another instruction (outside the chain)
    """

    iszeros_after_interleave_point = interleave_point // 2

    before_iszeros = ""
    for i in range(interleave_point):
        new = i + 2
        before_iszeros += f"""
        %cond{new} = iszero %cond{i + 1}"""

    after_iszeros = ""
    for i in range(iszeros_after_interleave_point):
        index = i + interleave_point + 1
        new = index + 1
        after_iszeros += f"""
        %cond{new} = iszero %cond{index}"""

    mstore_condition = interleave_point + 1
    jnz_condition = interleave_point + iszeros_after_interleave_point + 1

    pre = f"""
    main:
        %par = param
        %cond0 = add 64, %par
        %cond1 = iszero %cond0
        {before_iszeros}
        mstore %par, %cond{mstore_condition}
        {after_iszeros}
        jnz %cond{jnz_condition}, @then, @else
    then:
        %2 = add 10, %par
        sink %2
    else:
        %3 = add %cond0, %par
        sink %3
    """

    post_iszero = "%cond2 = iszero %cond1" if interleave_point % 2 == 1 else ""

    mstore_condition = (interleave_point) % 2 + 1
    jnz_condition = (interleave_point + iszeros_after_interleave_point + 1) % 2

    post = f"""
    main:
        %par = param
        %cond0 = add 64, %par
        %cond1 = iszero %cond0
        {post_iszero}
        mstore %par, %cond{mstore_condition}
        jnz %cond{jnz_condition}, @then, @else
    then:
        %2 = add 10, %par
        sink %2
    else:
        %3 = add %cond0, %par
        sink %3
    """

    _check_pre_post(pre, post)



def test_offsets():
    """
    Test of addition to offset rewrites
    """

    pre = """
    main:
        %par = param
        %1 = add @main, 0
        %2 = add 0, @main
        %3 = add %par, @main
        sink %1, %2, %3
    """

    post = """
    main:
        %par = param
        %1 = offset @main, 0

        ; TODO fix this
        ; the store is used directly because
        ; the parser does not see the label
        ; as literal
        %2 = store @main
        %3 = add %par, @main
        sink %1, %2, %3
    """

    _check_pre_post(pre, post)


# Test the case of https://github.com/vyperlang/vyper/issues/4288
def test_ssa_after_algebraic_optimization():
    code = """
@internal
def _do_math(x: uint256) -> uint256:
    value: uint256 = x
    result: uint256 = 0

    if (x >> 128 != 0):
        x >>= 128
    if (x >> 64 != 0):
        x >>= 64

    if 1 < value:
        result = 1

    return result

@external
def run() -> uint256:
    return self._do_math(10)
    """

    vyper.compile_code(code, output_formats=["bytecode"])

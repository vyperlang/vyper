from tests.venom_utils import PrePostChecker
from vyper.venom.passes import MakeSSA, Mem2Var

_check_pre_post = PrePostChecker([Mem2Var, MakeSSA])


def test_mem2var_alloca_without_initalization():
    pre = """
    main:
        %x = source
        %ptr = alloca 1, 32
        jmp @loop_header
    loop_header:
        %i = phi @main, %x, @loop_body, %nexti
        %cond = iszero %i
        jnz %i, @loop_body, @exit
    loop_body:
        %inv = sload 0
        %y = add %i, %inv
        mstore %ptr, %y
        %nexti = add %i, 1
        jmp @loop_header
    exit:
        %res = mload %ptr
        sink %res
    """

    post = """
    main:
        %x = source
        %ptr = alloca 1, 32

        ; by default set to zero to mimic
        ; uninitialized memory
        %alloca_ptr_0 = 0
        jmp @loop_header
    loop_header:
        %alloca_ptr_0:1 = phi @main, %alloca_ptr_0, @loop_body, %alloca_ptr_0:2
        %i:1 = phi @main, %x, @loop_body, %nexti
        %i = %i:1
        %cond = iszero %i:1
        jnz %i:1, @loop_body, @exit
    loop_body:
        %inv = sload 0
        %y = add %i:1, %inv
        %alloca_ptr_0:2 = %y
        %nexti = add %i:1, 1
        jmp @loop_header
    exit:
        %res = %alloca_ptr_0:1
        sink %res
    """

    _check_pre_post(pre, post)

from tests.venom_utils import PrePostChecker
from vyper.venom.passes import Mem2Var
from vyper.utils import CompilerPanic


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

    checker = PrePostChecker([Mem2Var])

    try:
        checker.run_passes(pre, pre)
    except CompilerPanic:  
        pass
    except:
        assert False

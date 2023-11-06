import pytest
from vyper.abi_types import ABI_Bytes, ABI_BytesM, ABI_DynamicArray, ABI_FixedMxN, ABI_GIntM, ABI_String
from vyper.exceptions import CompilerPanic


cases_invalid_types = [
    (
        ABI_GIntM,
        ( 
            (0, False),
            (7, False),
            (300, True),
            (300, False)
        ),
        CompilerPanic
    ),
    (
        ABI_FixedMxN,
        (            
            (0, 0, False),
            (8, 0, False),
            (256, 81, True),
            (300, 80, False)
        ),
        CompilerPanic
    ),
    (
        ABI_BytesM,
        (            
            (0,),
            (33,),
            (-10,),
        ),
        CompilerPanic
    ),
    (
        ABI_Bytes,
        (            
            (-1,),
            (-69,),
        ),
        CompilerPanic
    ),
    (
        ABI_DynamicArray,
        (            
            (ABI_GIntM(256, False), -1),
            (ABI_String(256), -10),
        ),
        CompilerPanic
    ),
]


@pytest.mark.parametrize("typ,params_variants,exc", cases_invalid_types)
def test_invalid_abi_types(assert_compile_failed, typ, params_variants, exc):
    # double parametrization cannot work because the 2nd dimension is variable
    for params in params_variants:
        assert_compile_failed(lambda: typ(*params), exc)

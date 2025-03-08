from subprocess import CalledProcessError
import pytest
from tests.hevm import hevm_check_venom
from tests.venom_utils import parse_from_basic_block

"""
Test that the hevm harness can actually detect faults,
not that hevm tests are spuriously passing due to incorrect test harness
setup.
"""

pytestmark = pytest.mark.hevm

def test_hevm_simple():
    code1 = """
    main:
        sink 1
    """
    code2 = """
    main:
        %2 = add 0, 1
        sink %2
    """
    hevm_check_venom(code1, code2)

def test_hevm_fault_simple():
    code1 = """
    main:
        sink 1
    """
    code2 = """
    main:
        sink 2
    """
 
    with pytest.raises(CalledProcessError):
        hevm_check_venom(code1, code2)

def test_hevm_branch():
    # test hevm detects branch always taken
    code1 = """
    main:
        sink 1
    """
    code2 = """
    main:
        %par = param
        jnz 1, @then, @else
    then:
        sink 1
    else:
        sink %par
    """
    hevm_check_venom(code1, code2)

def test_hevm_branch_fault():
    # test hevm detects branch always taken
    code1 = """
    main:
        sink 1
    """
    code2 = """
    main:
        %par = param
        %cond = iszero %par
        jnz %cond, @then, @else
    then:
        sink 1
    else:
        sink 2
    """
    with pytest.raises(CalledProcessError) as e:
        hevm_check_venom(code1, code2)

    # hevm-provided counterexample:
    assert "Calldata:\n  0x01" in e.value.stdout

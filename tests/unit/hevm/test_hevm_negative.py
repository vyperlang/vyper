import pytest

from tests.hevm import hevm_check_venom, hevm_raises

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

    with hevm_raises():
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
    with hevm_raises() as e:
        hevm_check_venom(code1, code2)

    # hevm-provided a counterexample:
    assert "Calldata:" in e.value.stdout


def test_hevm_detect_environment():
    # test hevm detects environment variables
    code1 = """
    main:
        sink 1
    """
    code2 = """
    main:
        %1 = address
        %2 = caller
        %3 = eq %1, %2
        assert %3
        sink 1
    """
    with hevm_raises() as e:
        hevm_check_venom(code1, code2)

    # hevm-provided counterexample:
    assert 'SymAddr "caller"' in e.value.stdout
    assert 'SymAddr "entrypoint"' in e.value.stdout


def test_hevm_detect_needle():
    # test hevm detects "needle-in-a-haystack" counterexamples
    code1 = """
    main:
        sink 0
    """
    code2 = """
    main:
        %1 = param
        %2 = add %1, 500
        %3 = iszero %2  ; should eval to nonzero except if param is (2**256 - 500)
        sink %3
    """
    with hevm_raises() as e:
        hevm_check_venom(code1, code2)

    # hevm-provided counterexample:
    assert "Calldata:" in e.value.stdout
    assert (
        "fe0c" in e.value.stdout
    )  # -500, but hevm with z3 solver reports the wrong counterexample

    # canary to let us know when hevm has fixed it:
    # cf. https://github.com/ethereum/hevm/pull/680
    assert "fffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffe0c" not in e.value.stdout
    # the correct assertion
    # assert hex(2**256 - 500) in e.value.stdout

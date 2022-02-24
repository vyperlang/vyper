import pytest


def test_basic_repeater(get_contract_with_gas_estimation):
    basic_repeater = """
@external
def repeat(z: int128) -> int128:
    x: int128 = 0
    for i in range(6):
        x = x + z
    return(x)
    """
    c = get_contract_with_gas_estimation(basic_repeater)
    assert c.repeat(9) == 54


def test_digit_reverser(get_contract_with_gas_estimation):
    digit_reverser = """
@external
def reverse_digits(x: int128) -> int128:
    dig: int128[6] = [0, 0, 0, 0, 0, 0]
    z: int128 = x
    for i in range(6):
        dig[i] = z % 10
        z = z / 10
    o: int128 = 0
    for i in range(6):
        o = o * 10 + dig[i]
    return o

    """

    c = get_contract_with_gas_estimation(digit_reverser)
    assert c.reverse_digits(123456) == 654321


def test_more_complex_repeater(get_contract_with_gas_estimation):
    more_complex_repeater = """
@external
def repeat() -> int128:
    out: int128 = 0
    for i in range(6):
        out = out * 10
        for j in range(4):
            out = out + j
    return(out)
    """

    c = get_contract_with_gas_estimation(more_complex_repeater)
    assert c.repeat() == 666666


@pytest.mark.parametrize("typ", ["int128", "uint256"])
def test_offset_repeater(get_contract_with_gas_estimation, typ):
    offset_repeater = f"""
@external
def sum() -> {typ}:
    out: {typ} = 0
    for i in range(80, 121):
        out = out + i
    return out
    """

    c = get_contract_with_gas_estimation(offset_repeater)
    assert c.sum() == 4100


@pytest.mark.parametrize("typ", ["int128", "uint256"])
def test_offset_repeater_2(get_contract_with_gas_estimation, typ):
    offset_repeater_2 = f"""
@external
def sum(frm: {typ}, to: {typ}) -> {typ}:
    out: {typ} = 0
    for i in range(frm, frm + 101):
        if i == to:
            break
        out = out + i
    return out
    """

    c = get_contract_with_gas_estimation(offset_repeater_2)
    assert c.sum(100, 99999) == 15150
    assert c.sum(70, 131) == 6100


def test_loop_call_priv(get_contract_with_gas_estimation):
    code = """
@internal
def _bar() -> bool:
    return True

@external
def foo() -> bool:
    for i in range(3):
        self._bar()
    return True
    """

    c = get_contract_with_gas_estimation(code)
    assert c.foo() is True


@pytest.mark.parametrize("typ", ["int128", "uint256"])
def test_return_inside_repeater(get_contract, typ):
    code = f"""
@internal
def _final(a: {typ}) -> {typ}:
    for i in range(10):
        for j in range(10):
            if j > 5:
                if i > a:
                    return i
    return 31337

@internal
def _middle(a: {typ}) -> {typ}:
    b: {typ} = self._final(a)
    return b

@external
def foo(a: {typ}) -> {typ}:
    b: {typ} = self._middle(a)
    return b
    """

    c = get_contract(code)
    assert c.foo(6) == 7
    assert c.foo(100) == 31337


@pytest.mark.parametrize("typ", ["int128", "uint256"])
def test_return_inside_nested_repeater(get_contract, typ):
    code = f"""
@internal
def _final(a: {typ}) -> {typ}:
    for i in range(10):
        for x in range(10):
            if i + x > a:
                return i + x
    return 31337

@internal
def _middle(a: {typ}) -> {typ}:
    b: {typ} = self._final(a)
    return b

@external
def foo(a: {typ}) -> {typ}:
    b: {typ} = self._middle(a)
    return b
    """

    c = get_contract(code)
    assert c.foo(14) == 15
    assert c.foo(100) == 31337


@pytest.fixture(params=["int128", "uint256"])
def test_return_void_nested_repeater_contract(request, get_contract):
    code = f"""
result: {request.param}
@internal
def _final(a: {request.param}):
    for i in range(10):
        for x in range(10):
            if i + x > a:
                self.result = i + x
                return
    self.result = 31337

@internal
def _middle(a: {request.param}):
    self._final(a)

@external
def foo(a: {request.param}) -> {request.param}:
    self._middle(a)
    return self.result
    """
    c = get_contract(code)
    return c


@pytest.mark.parametrize("val", range(20))
def test_return_void_nested_repeater(test_return_void_nested_repeater_contract, val):

    if val + 1 >= 19:
        assert test_return_void_nested_repeater_contract.foo(val) == 31337
    else:
        assert test_return_void_nested_repeater_contract.foo(val) == val + 1


@pytest.fixture(params=["int128", "uint256"])
def test_external_nested_repeater_contract(request, get_contract):
    code = f"""
@external
def foo(a: {request.param}) -> {request.param}:
    for i in range(10):
        for x in range(10):
            if i + x > a:
                return i + x
    return 31337
    """
    c = get_contract(code)
    return c


@pytest.mark.parametrize("val", range(20))
def test_external_nested_repeater(test_external_nested_repeater_contract, val):

    if val + 1 >= 19:
        assert test_external_nested_repeater_contract.foo(val) == 31337
    else:
        assert test_external_nested_repeater_contract.foo(val) == val + 1


@pytest.fixture(params=["int128", "uint256"])
def test_external_void_nested_repeater_contract(request, get_contract):
    # test return out of loop in void external function
    code = f"""
result: public({request.param})
@external
def foo(a: {request.param}):
    for i in range(10):
        for x in range(10):
            if i + x > a:
                self.result = i + x
                return
    self.result = 31337
    """
    c = get_contract(code)
    return c


@pytest.mark.parametrize("val", range(20))
def test_external_void_nested_repeater(test_external_void_nested_repeater_contract, val):

    test_external_void_nested_repeater_contract.foo(val, transact={})
    if val + 1 >= 19:
        assert test_external_void_nested_repeater_contract.result() == 31337
    else:
        assert test_external_void_nested_repeater_contract.result() == val + 1


@pytest.mark.parametrize("typ", ["int128", "uint256"])
def test_breaks_and_returns_inside_nested_repeater(get_contract, typ):
    code = f"""
@internal
def _final(a: {typ}) -> {typ}:
    for i in range(10):
        for x in range(10):
            if a < 2:
                break
            return 6
        if a == 1:
            break
        return 31337

    return 666

@internal
def _middle(a: {typ}) -> {typ}:
    b: {typ} = self._final(a)
    return b

@external
def foo(a: {typ}) -> {typ}:
    b: {typ} = self._middle(a)
    return b
    """

    c = get_contract(code)
    assert c.foo(100) == 6
    assert c.foo(1) == 666
    assert c.foo(0) == 31337

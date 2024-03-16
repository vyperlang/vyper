import pytest


def test_basic_repeater(get_contract_with_gas_estimation):
    basic_repeater = """
@external
def repeat(z: int128) -> int128:
    x: int128 = 0
    for i: int128 in range(6):
        x = x + z
    return(x)
    """
    c = get_contract_with_gas_estimation(basic_repeater)
    assert c.repeat(9) == 54


def test_range_bound(get_contract, tx_failed):
    code = """
@external
def repeat(n: uint256) -> uint256:
    x: uint256 = 0
    for i: uint256 in range(n, bound=6):
        x += i + 1
    return x
    """
    c = get_contract(code)
    for n in range(7):
        assert c.repeat(n) == sum(i + 1 for i in range(n))

    # check codegen inserts assertion for n greater than bound
    with tx_failed():
        c.repeat(7)


def test_range_bound_constant_end(get_contract, tx_failed):
    code = """
@external
def repeat(n: uint256) -> uint256:
    x: uint256 = 0
    for i: uint256 in range(n, 7, bound=6):
        x += i + 1
    return x
    """
    c = get_contract(code)
    for n in range(1, 5):
        assert c.repeat(n) == sum(i + 1 for i in range(n, 7))

    # check assertion for `start <= end`
    with tx_failed():
        c.repeat(8)
    # check assertion for `start + bound <= end`
    with tx_failed():
        c.repeat(0)


def test_range_bound_two_args(get_contract, tx_failed):
    code = """
@external
def repeat(n: uint256) -> uint256:
    x: uint256 = 0
    for i: uint256 in range(1, n, bound=6):
        x += i + 1
    return x
    """
    c = get_contract(code)
    for n in range(1, 8):
        assert c.repeat(n) == sum(i + 1 for i in range(1, n))

    # check assertion for `start <= end`
    with tx_failed():
        c.repeat(0)

    # check codegen inserts assertion for `start + bound <= end`
    with tx_failed():
        c.repeat(8)


def test_range_bound_two_runtime_args(get_contract, tx_failed):
    code = """
@external
def repeat(start: uint256, end: uint256) -> uint256:
    x: uint256 = 0
    for i: uint256 in range(start, end, bound=6):
        x += i
    return x
    """
    c = get_contract(code)
    for n in range(0, 7):
        assert c.repeat(0, n) == sum(range(0, n))
        assert c.repeat(n, n * 2) == sum(range(n, n * 2))

    # check assertion for `start <= end`
    with tx_failed():
        c.repeat(1, 0)
    with tx_failed():
        c.repeat(7, 0)
    with tx_failed():
        c.repeat(8, 7)

    # check codegen inserts assertion for `start + bound <= end`
    with tx_failed():
        c.repeat(0, 7)
    with tx_failed():
        c.repeat(14, 21)


def test_range_overflow(get_contract, tx_failed):
    code = """
@external
def get_last(start: uint256, end: uint256) -> uint256:
    x: uint256 = 0
    for i: uint256 in range(start, end, bound=6):
        x = i
    return x
    """
    c = get_contract(code)
    UINT_MAX = 2**256 - 1
    assert c.get_last(UINT_MAX, UINT_MAX) == 0  # initial value of x

    for n in range(1, 6):
        assert c.get_last(UINT_MAX - n, UINT_MAX) == UINT_MAX - 1

    # check for `start + bound <= end`, overflow cases
    for n in range(1, 7):
        with tx_failed():
            c.get_last(UINT_MAX - n, 0)
        with tx_failed():
            c.get_last(UINT_MAX, UINT_MAX - n)


def test_digit_reverser(get_contract_with_gas_estimation):
    digit_reverser = """
@external
def reverse_digits(x: int128) -> int128:
    dig: int128[6] = [0, 0, 0, 0, 0, 0]
    z: int128 = x
    for i: uint256 in range(6):
        dig[i] = z % 10
        z = z // 10
    o: int128 = 0
    for i: uint256 in range(6):
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
    for i: uint256 in range(6):
        out = out * 10
        for j: int128 in range(4):
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
    for i: {typ} in range(80, 121):
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
    for i: {typ} in range(frm, frm + 101, bound=101):
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
    for i: uint256 in range(3):
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
    for i: {typ} in range(10):
        for j: {typ} in range(10):
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


@pytest.mark.parametrize("typ", ["uint8", "int128", "uint256"])
def test_for_range_edge(get_contract, typ):
    """
    Check that we can get to the upper range of an integer.
    Note that to avoid overflow in the bounds check for range(),
    we need to calculate i+1 inside the loop.
    """
    code = f"""
@external
def test():
    found: bool = False
    x: {typ} = max_value({typ})
    for i: {typ} in range(x - 1, x, bound=1):
        if i + 1 == max_value({typ}):
            found = True
    assert found

    found = False
    x = max_value({typ}) - 1
    for i: {typ} in range(x - 1, x + 1, bound=2):
        if i + 1 == max_value({typ}):
            found = True
    assert found
    """
    c = get_contract(code)
    c.test()


@pytest.mark.parametrize("typ", ["uint8", "int128", "uint256"])
def test_for_range_oob_check(get_contract, tx_failed, typ):
    code = f"""
@external
def test():
    x: {typ} = max_value({typ})
    for i: {typ} in range(x, x + 2, bound=2):
        pass
    """
    c = get_contract(code)
    with tx_failed():
        c.test()


@pytest.mark.parametrize("typ", ["int128", "uint256"])
def test_return_inside_nested_repeater(get_contract, typ):
    code = f"""
@internal
def _final(a: {typ}) -> {typ}:
    for i: {typ} in range(10):
        for x: {typ} in range(10):
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


@pytest.mark.parametrize("typ", ["int128", "uint256"])
@pytest.mark.parametrize("val", range(20))
def test_return_void_nested_repeater(get_contract, typ, val):
    code = f"""
result: {typ}
@internal
def _final(a: {typ}):
    for i: {typ} in range(10):
        for x: {typ} in range(10):
            if i + x > a:
                self.result = i + x
                return
    self.result = 31337

@internal
def _middle(a: {typ}):
    self._final(a)

@external
def foo(a: {typ}) -> {typ}:
    self._middle(a)
    return self.result
    """
    c = get_contract(code)
    if val + 1 >= 19:
        assert c.foo(val) == 31337
    else:
        assert c.foo(val) == val + 1


@pytest.mark.parametrize("typ", ["int128", "uint256"])
@pytest.mark.parametrize("val", range(20))
def test_external_nested_repeater(get_contract, typ, val):
    code = f"""
@external
def foo(a: {typ}) -> {typ}:
    for i: {typ} in range(10):
        for x: {typ} in range(10):
            if i + x > a:
                return i + x
    return 31337
    """
    c = get_contract(code)
    if val + 1 >= 19:
        assert c.foo(val) == 31337
    else:
        assert c.foo(val) == val + 1


@pytest.mark.parametrize("typ", ["int128", "uint256"])
@pytest.mark.parametrize("val", range(20))
def test_external_void_nested_repeater(get_contract, typ, val):
    # test return out of loop in void external function
    code = f"""
result: public({typ})
@external
def foo(a: {typ}):
    for i: {typ} in range(10):
        for x: {typ} in range(10):
            if i + x > a:
                self.result = i + x
                return
    self.result = 31337
    """
    c = get_contract(code)
    c.foo(val, transact={})
    if val + 1 >= 19:
        assert c.result() == 31337
    else:
        assert c.result() == val + 1


@pytest.mark.parametrize("typ", ["int128", "uint256"])
def test_breaks_and_returns_inside_nested_repeater(get_contract, typ):
    code = f"""
@internal
def _final(a: {typ}) -> {typ}:
    for i: {typ} in range(10):
        for x: {typ} in range(10):
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


def test_for_range_signed_int_overflow(get_contract, tx_failed):
    code = """
@external
def foo() -> DynArray[int256, 10]:
    res: DynArray[int256, 10] = empty(DynArray[int256, 10])
    x:int256 = max_value(int256)
    y:int256 = min_value(int256)+2
    for i:int256 in range(x,y , bound=10):
        res.append(i)
    return res
    """
    c = get_contract(code)
    with tx_failed():
        c.foo()

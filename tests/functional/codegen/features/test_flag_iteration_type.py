def test_iterate_over_flag_type(get_contract):
    code = """
flag Permission:
    A
    B
    C

@pure
@external
def sum_mask() -> uint256:
    acc: uint256 = 0
    for p: Permission in Permission.__values__:
        acc = acc | convert(p, uint256)
    return acc
"""
    c = get_contract(code)
    # 1 | 2 | 4 = 7
    assert c.sum_mask() == 7


def test_iterate_over_flag_type_count(get_contract):
    code = """
flag Permission:
    A
    B
    C
    D

@pure
@external
def count() -> uint256:
    cnt: uint256 = 0
    for p: Permission in Permission.__values__:
        cnt += 1
    return cnt
"""
    c = get_contract(code)
    assert c.count() == 4


def test_iterate_over_flag_type_order(get_contract):
    code = """
flag Permission:
    A
    B
    C
    D

@pure
@external
def order_sum() -> uint256:
    acc: uint256 = 0
    idx: uint256 = 0
    for p: Permission in Permission.__values__:
        acc = acc + (convert(p, uint256) << idx)
        idx += 1
    return acc
"""
    c = get_contract(code)
    # 1 + (2<<1) + (4<<2) + (8<<3) = 1 + 4 + 16 + 64 = 85
    assert c.order_sum() == 85


def test_flag_iter_target_type_mismatch(assert_compile_failed, get_contract):
    from vyper.exceptions import TypeMismatch

    code = """
flag A:
    X
flag B:
    Y

@pure
@external
def f() -> uint256:
    s: uint256 = 0
    for p: B in A.__values__:
        s += convert(p, uint256)
    return s
"""
    assert_compile_failed(lambda: get_contract(code), TypeMismatch)


def test_flag_iter_invalid_iterator(assert_compile_failed, get_contract):
    from vyper.exceptions import InvalidType

    code = """
flag P:
    A

@pure
@external
def f() -> uint256:
    s: uint256 = 0
    for p: P in 5:
        s += 1
    return s
"""
    assert_compile_failed(lambda: get_contract(code), InvalidType)


def test_flag_iter_wrong_target_type(assert_compile_failed, get_contract):
    from vyper.exceptions import TypeMismatch

    code = """
flag P:
    A
    B

@pure
@external
def f() -> uint256:
    s: uint256 = 0
    for p: uint256 in P.__values__:
        s += p  # wrong type; loop var must be P
    return s
"""
    assert_compile_failed(lambda: get_contract(code), TypeMismatch)


def test_flag_instance_member_access(assert_compile_failed, get_contract):
    from vyper.exceptions import UnknownAttribute

    code = """
flag P:
    A
    B

@pure
@external
def f(p: P) -> uint256:
    return convert(p.A, uint256)
"""
    assert_compile_failed(lambda: get_contract(code), UnknownAttribute)


def test_nested_flag_type_iteration(get_contract):
    code = """
flag A:
    X
    Y
    Z

flag B:
    P
    Q

@pure
@external
def product_sum() -> uint256:
    s: uint256 = 0
    for a: A in A.__values__:
        for b: B in B.__values__:
            s += convert(a, uint256) * convert(b, uint256)
    return s
"""
    c = get_contract(code)
    # a in {1,2,4}, b in {1,2} => (1+2+4)*(1+2) = 7*3 = 21
    assert c.product_sum() == 21


def test_clear_basic_type(get_contract_with_gas_estimation):
    contracts = [
    """
foobar: int128

@public
def foo():
    self.foobar = 1
    bar: int128 = 1

    clear(self.foobar)
    clear(bar)

    assert self.foobar == 0
    assert bar == 0
    """,
    """
foobar: uint256

@public
def foo():
    self.foobar = 1
    bar: uint256 = 1

    clear(self.foobar)
    clear(bar)

    assert self.foobar == 0
    assert bar == 0
    """,
    """
foobar: bool

@public
def foo():
    self.foobar = True
    bar: bool = True

    clear(self.foobar)
    clear(bar)

    assert self.foobar == False
    assert bar == False
    """,
    """
foobar: decimal

@public
def foo():
    self.foobar = 1.0
    bar: decimal = 1.0

    clear(self.foobar)
    clear(bar)

    assert self.foobar == 0.0
    assert bar == 0.0
    """,
    """
foobar: bytes32

@public
def foo():
    self.foobar = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF
    bar: bytes32 = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF

    clear(self.foobar)
    clear(bar)

    assert self.foobar == 0x0000000000000000000000000000000000000000000000000000000000000000
    assert bar == 0x0000000000000000000000000000000000000000000000000000000000000000
    """,
    """
foobar: address

@public
def foo():
    self.foobar = msg.sender
    bar: address = msg.sender

    clear(self.foobar)
    clear(bar)

    assert self.foobar == ZERO_ADDRESS
    assert bar == ZERO_ADDRESS
    """
    ]

    for contract in contracts:
        c = get_contract_with_gas_estimation(contract)
        c.foo()


def test_clear_basic_type_lists(get_contract_with_gas_estimation):
    contracts = [
    """
foobar: int128[3]

@public
def foo():
    self.foobar = [1, 2, 3]
    bar: int128[3] = [1, 2, 3]

    clear(self.foobar)
    clear(bar)

    assert self.foobar[0] == 0
    assert self.foobar[1] == 0
    assert self.foobar[2] == 0
    assert bar[0] == 0
    assert bar[1] == 0
    assert bar[2] == 0
    """,
    """
foobar: uint256[3]

@public
def foo():
    self.foobar = [1, 2, 3]
    bar: uint256[3] = [1, 2, 3]

    clear(self.foobar)
    clear(bar)

    assert self.foobar[0] == 0
    assert self.foobar[1] == 0
    assert self.foobar[2] == 0
    assert bar[0] == 0
    assert bar[1] == 0
    assert bar[2] == 0
    """,
    """
foobar: bool[3]

@public
def foo():
    self.foobar = [True, True, True]
    bar: bool[3] = [True, True, True]

    clear(self.foobar)
    clear(bar)

    assert self.foobar[0] == False
    assert self.foobar[1] == False
    assert self.foobar[2] == False
    assert bar[0] == False
    assert bar[1] == False
    assert bar[2] == False
    """,
    """
foobar: decimal[3]

@public
def foo():
    self.foobar = [1.0, 2.0, 3.0]
    bar: decimal[3] = [1.0, 2.0, 3.0]

    clear(self.foobar)
    clear(bar)

    assert self.foobar[0] == 0.0
    assert self.foobar[1] == 0.0
    assert self.foobar[2] == 0.0
    assert bar[0] == 0.0
    assert bar[1] == 0.0
    assert bar[2] == 0.0
    """,
    """
foobar: bytes32[3]

@public
def foo():
    self.foobar = [
        0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF,
        0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF00000000000000000000000000000000,
        0x00000000000000000000000000000000FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF
    ]
    bar: bytes32[3] = [
        0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF,
        0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF00000000000000000000000000000000,
        0x00000000000000000000000000000000FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF
    ]

    clear(self.foobar)
    clear(bar)

    assert self.foobar[0] == 0x0000000000000000000000000000000000000000000000000000000000000000
    assert self.foobar[1] == 0x0000000000000000000000000000000000000000000000000000000000000000
    assert self.foobar[2] == 0x0000000000000000000000000000000000000000000000000000000000000000
    assert bar[0] == 0x0000000000000000000000000000000000000000000000000000000000000000
    assert bar[1] == 0x0000000000000000000000000000000000000000000000000000000000000000
    assert bar[2] == 0x0000000000000000000000000000000000000000000000000000000000000000
    """,
    """
foobar: address[3]

@public
def foo():
    self.foobar = [msg.sender, msg.sender, msg.sender]
    bar: address[3] = [msg.sender, msg.sender, msg.sender]

    clear(self.foobar)
    clear(bar)

    assert self.foobar[0] == ZERO_ADDRESS
    assert self.foobar[1] == ZERO_ADDRESS
    assert self.foobar[2] == ZERO_ADDRESS
    assert bar[0] == ZERO_ADDRESS
    assert bar[1] == ZERO_ADDRESS
    assert bar[2] == ZERO_ADDRESS
    """
    ]

    for contract in contracts:
        c = get_contract_with_gas_estimation(contract)
        c.foo()


def test_clear_literals(assert_compile_failed, get_contract_with_gas_estimation):
    contracts = [
    """
@public
def foo():
    clear(1)
    """,
    """
@public
def foo():
    clear(True)
    """,
    """
@public
def foo():
    clear(1.0)
    """,
    """
@public
def foo():
    clear(0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF)
    """,
    """
@public
def foo():
    clear(0xF5D4020dCA6a62bB1efFcC9212AAF3c9819E30D7)
    """
    ]

    for contract in contracts:
        assert_compile_failed(
            lambda: get_contract_with_gas_estimation(contract),
            Exception
        )


def test_clear_bytes(get_contract_with_gas_estimation):
    code = """
foobar: bytes[5]

@public
def foo() -> (bytes[5], bytes[5]):
    self.foobar = 'Hello'
    bar: bytes[5] = 'World'

    clear(self.foobar)
    clear(bar)

    return (self.foobar, bar)
    """

    c = get_contract_with_gas_estimation(code)
    a, b = c.foo()
    assert a == b''
    assert b == b''


def test_clear_struct(get_contract_with_gas_estimation):
    code = """
foobar: {
    a: int128,
    b: uint256,
    c: bool,
    d: decimal,
    e: bytes32,
    f: address
}

@public
def foo():
    self.foobar = {
        a: 1,
        b: 2,
        c: True,
        d: 3.0,
        e: 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF,
        f: msg.sender
    }
    bar: {
        a: int128,
        b: uint256,
        c: bool,
        d: decimal,
        e: bytes32,
        f: address
    } = {
        a: 1,
        b: 2,
        c: True,
        d: 3.0,
        e: 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF,
        f: msg.sender
    }

    clear(self.foobar)
    clear(bar)

    assert self.foobar.a == 0
    assert self.foobar.b == 0
    assert self.foobar.c == False
    assert self.foobar.d == 0.0
    assert self.foobar.e == 0x0000000000000000000000000000000000000000000000000000000000000000
    assert self.foobar.f == ZERO_ADDRESS

    assert bar.a == 0
    assert bar.b == 0
    assert bar.c == False
    assert bar.d == 0.0
    assert bar.e == 0x0000000000000000000000000000000000000000000000000000000000000000
    assert bar.f == ZERO_ADDRESS
    """

    c = get_contract_with_gas_estimation(code)
    c.foo()

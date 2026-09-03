import json

import pytest

from vyper import compiler
from vyper.exceptions import (
    InstantiationException,
    InvalidAttribute,
    StructureException,
    TypeMismatch,
    UnknownAttribute,
)

fail_list = [
    """
event Bar:
    _value: int128[4]

x: decimal[4]

@external
def foo():
    log Bar(_value=self.x)
    """,
    """
event Bar:
    _value: int128[4]

@external
def foo():
    x: decimal[4] = [0.0, 0.0, 0.0, 0.0]
    log Bar(_value=x)
    """,
    """
struct Foo:
    pass

@external
def foo():
    log Foo  # missing parens
    """,
    """
event Test:
    n: uint256

@external
def test():
    log Test(n=-7)
   """,
]


@pytest.mark.parametrize("bad_code", fail_list)
def test_logging_fail(bad_code):
    with pytest.raises((TypeMismatch, StructureException)):
        compiler.compile_code(bad_code)


def test_logging_fail_mixed_positional_kwargs():
    code = """
event Test:
    n: uint256
    o: uint256

@external
def test():
    log Test(7, o=12)
    """
    with pytest.raises(InstantiationException):
        compiler.compile_code(code)


def test_logging_fail_unknown_kwarg():
    code = """
event Test:
    n: uint256

@external
def test():
    log Test(n=7, o=12)
    """
    with pytest.raises(UnknownAttribute):
        compiler.compile_code(code)


def test_logging_fail_missing_kwarg():
    code = """
event Test:
    n: uint256
    o: uint256

@external
def test():
    log Test(n=7)
    """
    with pytest.raises(InstantiationException):
        compiler.compile_code(code)


def test_logging_fail_kwargs_out_of_order():
    code = """
event Test:
    n: uint256
    o: uint256

@external
def test():
    log Test(o=12, n=7)
    """
    with pytest.raises(InvalidAttribute):
        compiler.compile_code(code)


@pytest.mark.parametrize("mutability", ["@pure", "@view"])
@pytest.mark.parametrize("visibility", ["@internal", "@external"])
def test_logging_from_non_mutable(mutability, visibility):
    code = f"""
event Test:
    n: uint256

{visibility}
{mutability}
def test():
    log Test(n=1)
    """
    with pytest.raises(StructureException):
        compiler.compile_code(code)


def test_logging_with_positional_args(get_contract, get_logs):
    # TODO: Remove when positional arguments are fully deprecated
    code = """
event Test:
    n: uint256

@external
def test():
    log Test(1)
    """
    c = get_contract(code)
    c.test()
    (log,) = get_logs(c, "Test")
    assert log.args.n == 1


@pytest.mark.parametrize(
    "typ",
    ["uint256[2]", "DynArray[uint256, 3]", "DynArray[uint256, INF]", "(uint256, uint256)", "Foo"],
)
def test_indexed_reference_type_fails(typ):
    code = f"""
struct Foo:
    a: uint256

event E:
    x: indexed({typ})

@external
def foo():
    log E(x=empty({typ}))
"""
    with pytest.raises(StructureException) as e:
        compiler.compile_code(code)
    assert e.value.message == "Event indexes may only be value types"


@pytest.mark.parametrize(
    ("typ", "value"),
    [
        ("uint256", "1"),
        ("int128", "-1"),
        ("bool", "True"),
        ("address", "msg.sender"),
        ("bytes32", "empty(bytes32)"),
        ("bytes4", "empty(bytes4)"),
        ("Flg", "Flg.A"),
        ("IFoo", "IFoo(msg.sender)"),
        ("Bytes[10]", "b'ab'"),
        ("String[10]", "'ab'"),
    ],
)
def test_indexed_value_type(typ, value):
    code = f"""
flag Flg:
    A

interface IFoo:
    def f(): nonpayable

event E:
    x: indexed({typ})

@external
def foo():
    log E(x={value})
    """
    assert compiler.compile_code(code) is not None


@pytest.mark.parametrize(("typ", "value"), [("Bytes[INF]", "b'ab'"), ("String[INF]", "'ab'")])
def test_indexed_inf_bytestring(compile_inf_code, typ, value):
    code = f"""
event E:
    x: indexed({typ})

@external
def foo():
    log E(x={value})
    """
    compile_inf_code(code)


def test_json_abi_indexed_reference_type_fails(make_input_bundle):
    # json abi events bypass `EventT.from_EventDef`; the log-site check
    # rejects an indexed member without a topic encoding for them too
    abi = [
        {
            "anonymous": False,
            "inputs": [{"indexed": True, "name": "x", "type": "uint256[2]"}],
            "name": "EvArr",
            "type": "event",
        }
    ]
    code = """
import JSONInterface

@external
def foo():
    log JSONInterface.EvArr(x=[1, 2])
    """
    input_bundle = make_input_bundle({"JSONInterface.json": json.dumps(abi)})
    with pytest.raises(StructureException) as e:
        compiler.compile_code(code, input_bundle=input_bundle)
    assert e.value.message == "Event indexes may only be value types"

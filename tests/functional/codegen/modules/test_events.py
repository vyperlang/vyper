import pytest


def test_module_event(get_contract, make_input_bundle, get_logs):
    # log from a module
    lib1 = """
event MyEvent:
    pass

@internal
def foo():
    log MyEvent()
    """
    main = """
import lib1

@external
def bar():
    lib1.foo()
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1})
    c = get_contract(main, input_bundle=input_bundle)
    c.bar()
    logs = get_logs(c, "MyEvent")
    assert len(logs) == 1


def test_module_event2(get_contract, make_input_bundle, get_logs):
    # log a module event from main contract
    lib1 = """
event MyEvent:
    x: uint256
    """
    main = """
import lib1

@external
def bar():
    log lib1.MyEvent(5)
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1})
    c = get_contract(main, input_bundle=input_bundle)
    c.bar()
    (log,) = get_logs(c, "MyEvent")
    assert log.args.x == 5


def test_module_event_indexed(get_contract, make_input_bundle, get_logs):
    lib1 = """
event MyEvent:
    x: uint256
    y: indexed(uint256)

@internal
def foo():
    log MyEvent(x=5, y=6)
    """
    main = """
import lib1

@external
def bar():
    lib1.foo()
    """
    input_bundle = make_input_bundle({"lib1.vy": lib1})
    c = get_contract(main, input_bundle=input_bundle)
    c.bar()
    (log,) = get_logs(c, "MyEvent")
    assert log.args.x == 5
    assert log.args.y == 6


@pytest.mark.parametrize(
    "member_type,value",
    [
        ("Bytes[...]", b"ab"),
        ("String[...]", "ab"),
        ("DynArray[uint256, ...]", []),
        ("DynArray[uint256, ...]", [1, 2]),
        ("DynArray[Bytes[...], 5]", [b"ab"]),
    ],
)
def test_interface_wildcard_event(get_contract, make_input_bundle, get_logs, member_type, value):
    interface = f"""
event E:
    xs: {member_type}
    """
    code = f"""
import IW

@external
def emit():
    log IW.E(xs={value!r})
    """
    input_bundle = make_input_bundle({"IW.vyi": interface})
    c = get_contract(code, input_bundle=input_bundle)
    c.emit()
    (log,) = get_logs(c, "E")
    assert log.args.xs == value


def test_interface_wildcard_event_empty_nested(
    get_contract, make_input_bundle, get_logs, experimental_codegen
):
    # No element bound can be inferred from [], so Bytes[...] resolves to INF.
    if not experimental_codegen:
        pytest.skip("unbounded sequence types require --experimental-codegen")
    interface = """
event E:
    xs: DynArray[Bytes[...], 5]
    """
    code = """
import IW

@external
def emit():
    log IW.E(xs=[])
    """
    input_bundle = make_input_bundle({"IW.vyi": interface})
    c = get_contract(code, input_bundle=input_bundle)
    c.emit()
    (log,) = get_logs(c, "E")
    assert log.args.xs == []

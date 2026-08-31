import pytest

from vyper.exceptions import EventDeclarationException, TypeMismatch
from vyper.semantics.types.module import InterfaceT
from vyper.semantics.types.user import EventT
from vyper.utils import keccak256


def keccak256_int(signature_str):
    return int.from_bytes(keccak256(signature_str.encode()), "big")


# TODO: refactor these to all use keccak256_int util instead of hardcoded constants
EVENT_ID_TESTS = [
    (
        "event MyLog: pass",
        # MyLog()
        0x375227D322F87546308335EBD7DD99C33B9D50E4DA37CE574E20471DA5E5CBE3,
    ),
    (
        """event MyLog:
    arg1: indexed(Bytes[3])""",
        # MyLog(bytes),
        0xA1BE0F4C7DDB427F96E8F62379A428E182221B02E4C3A77CC1DF3052E5D4D4BD,
    ),
    (
        """event MyLog:
    arg1: indexed(int128)
    arg2: indexed(bool)
    arg3: indexed(address)""",
        # MyLog(int128,bool,address)
        0x6D352FAAAA2891008D60036040A38A3093DD1ED2D080EEDF1E429A2F2F8D8278,
    ),
    (
        """event Potato:
    arg1: indexed(Bytes[3])
    arg2: Bytes[4]
    arg3: indexed(address)
    arg4: indexed(int128)
    """,
        # Potato(bytes,bytes,address,int128)
        0xDC82805040581BD5F35160514B94A70D2F4A1574893F1349C84472C929BD1DF0,
    ),
    (
        """event Sausage:
    arg1: int128[2]
    arg2: uint256[3]
    arg3: int128[2][2]""",
        # Sausage(int128[2],uint256[3],int128[2][2])
        0x8E4F55680D33B209630C1C6E7EFE010DB3F4CB68AB9E3D62ABB83166E41F1844,
    ),
    (
        """event MyLog:
    arg1: Bytes[4]
    arg2: indexed(String[100])
    arg3: Bytes[33]""",
        # MyLog(bytes,string,bytes)
        0x7C3BB2850EE5EAFB776ACB6E32BD31E7292FA93036CDB23D2B07AE026476F05B,
    ),
    (
        """event FooBar:
    arg1: int128
    arg2: Bytes[4]
    arg3: Bytes[39912]
    arg4: address
    arg5: address
    arg6: uint256[3]""",
        # FooBar(int128,bytes,bytes,address,address,uint256[3])
        0xD7BA39F8B5428B9F3102921170C6AE4578AA5536E05E5A86EDD36BEA67AEDD8A,
    ),
    (
        """event Nonsense:
    a: Bytes[666]
    b: int128[4][38]
    c: address[3]
    d: uint256
    e: String[1]""",
        # Nonsense(bytes,int128[4][38],address[3],uint256,string)
        0xEE1C420D3504F8A563AA99C8341A41C4C2A1A7F35665EE2F5F341CB8F451B5FC,
    ),
    (
        """event Bar:
    a: decimal[4]""",
        keccak256_int("Bar(int168[4])"),
    ),
    (
        """event Rtadr:
    a: indexed(decimal)
    b: decimal[2][5]
    c: Bytes[4]
    d: decimal[666]""",
        keccak256_int("Rtadr(int168,int168[2][5],bytes,int168[666])"),
    ),
]


@pytest.mark.parametrize("source,signature_hash", EVENT_ID_TESTS)
def test_event_id(build_node, source, signature_hash):
    node = build_node(source)
    event = EventT.from_EventDef(node)

    assert event.event_id == signature_hash


def _event_abi(*inputs):
    return {
        "type": "event",
        "name": "E",
        "anonymous": False,
        "inputs": [
            {"name": f"arg{i}", "type": t, "indexed": idx} for i, (t, idx) in enumerate(inputs)
        ],
    }


@pytest.mark.parametrize("bad_type", ["uint256[3]", "uint256[2][2]"])
def test_from_abi_indexed_non_value_type_rejected(bad_type):
    with pytest.raises(TypeMismatch) as excinfo:
        EventT.from_abi(_event_abi((bad_type, True)))
    assert excinfo.value.message == "Event indexes may only be value types"


@pytest.mark.parametrize(
    "good_type", ["uint256", "int128", "address", "bool", "bytes32", "bytes", "string"]
)
def test_from_abi_indexed_value_types_accepted(good_type):
    event = EventT.from_abi(_event_abi((good_type, True)))
    assert event.indexed == [True]


def test_from_abi_more_than_three_indexed_rejected():
    abi = _event_abi(("uint256", True), ("uint256", True), ("uint256", True), ("uint256", True))
    with pytest.raises(EventDeclarationException) as excinfo:
        EventT.from_abi(abi)
    assert excinfo.value.message == "Event cannot have more than three indexed arguments"


def test_from_abi_anonymous_four_indexed_accepted():
    abi = _event_abi(("uint256", True), ("uint256", True), ("uint256", True), ("uint256", True))
    abi["anonymous"] = True
    event = EventT.from_abi(abi)
    assert event.indexed == [True, True, True, True]


def test_from_abi_anonymous_more_than_four_indexed_rejected():
    abi = _event_abi(
        ("uint256", True),
        ("uint256", True),
        ("uint256", True),
        ("uint256", True),
        ("uint256", True),
    )
    abi["anonymous"] = True
    with pytest.raises(EventDeclarationException) as excinfo:
        EventT.from_abi(abi)
    assert excinfo.value.message == "Anonymous event cannot have more than four indexed arguments"


def test_from_json_abi_surfaces_indexed_type_error():
    abi = [_event_abi(("uint256[3]", True))]
    with pytest.raises(TypeMismatch) as excinfo:
        InterfaceT.from_json_abi("I", abi)
    assert excinfo.value.message == "Event indexes may only be value types"

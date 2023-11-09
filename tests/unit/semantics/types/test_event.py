import pytest

from vyper.semantics.types.user import EventT

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
    c: indexed(address[3])
    d: uint256
    e: String[1]""",
        # Nonsense(bytes,int128[4][38],address[3],uint256,string)
        0xEE1C420D3504F8A563AA99C8341A41C4C2A1A7F35665EE2F5F341CB8F451B5FC,
    ),
    (
        """event Bar:
    a: decimal[4]""",
        # Bar(fixed168x10[4])
        0x7F5D3D77DC11EED2D256D513EF1916FBA342AD13DD629E3C2FF3BD1BAEADF932,
    ),
    (
        """event Rtadr:
    a: indexed(decimal)
    b: decimal[2][5]
    c: Bytes[4]
    d: decimal[666]""",
        # Rtadr(fixed168x10,fixed168x10[2][5],bytes,fixed168x10[666])
        0x20B4E04949A8E3B03C8DECC09D8B18B271D42E66F83B9FAA7B75EA7E22E27177,
    ),
]


@pytest.mark.parametrize("source,signature_hash", EVENT_ID_TESTS)
def test_event_id(build_node, source, signature_hash):
    node = build_node(source)
    event = EventT.from_EventDef(node)

    assert event.event_id == signature_hash

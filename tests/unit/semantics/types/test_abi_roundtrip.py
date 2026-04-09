"""
Roundtrip tests: compile Vyper contracts to ABI JSON, then parse back
via from_abi / from_json_abi to verify Vyper can consume its own output.
"""

from vyper.compiler.output import build_abi_output
from vyper.compiler.phases import CompilerData
from vyper.semantics.types.function import ContractFunctionT
from vyper.semantics.types.module import InterfaceT
from vyper.semantics.types.user import EventT


def _compile_abi(source: str) -> list[dict]:
    data = CompilerData(source)
    return build_abi_output(data)


FALLBACK_ONLY = """
@payable
@external
def __default__():
    pass
"""

CONSTRUCTOR_ONLY = """
x: int128

@deploy
def __init__():
    self.x = 1
"""

SIMPLE_FUNCTION = """
@external
@view
def add(a: uint256, b: uint256) -> uint256:
    return a + b
"""

NO_ARGS_NO_RETURN = """
@external
def ping():
    pass
"""

MULTIPLE_FUNCTIONS_AND_EVENTS = """
event Transfer:
    sender: indexed(address)
    receiver: indexed(address)
    amount: uint256

event Approval:
    owner: indexed(address)
    spender: indexed(address)
    amount: uint256

@external
@view
def balanceOf(owner: address) -> uint256:
    return 0

@external
def transfer(to: address, amount: uint256) -> bool:
    log Transfer(sender=msg.sender, receiver=to, amount=amount)
    return True
"""

DEFAULT_ARGS = """
@external
@view
def foo(a: uint256, b: uint256 = 10, c: uint256 = 20) -> uint256:
    return a + b + c
"""

PUBLIC_STATE_VAR = """
totalSupply: public(uint256)
owner: public(address)
"""

TUPLE_RETURN = """
@external
@view
def getValues() -> (uint256, address, bool):
    return 0, empty(address), False
"""

CONSTRUCTOR_WITH_ARGS = """
owner: address

@deploy
def __init__(initial_owner: address):
    self.owner = initial_owner
"""

MIXED_CONTRACT = """
event Deposit:
    sender: indexed(address)
    amount: uint256

deposited: public(uint256)

@deploy
def __init__():
    self.deposited = 0

@payable
@external
def __default__():
    self.deposited += msg.value
    log Deposit(sender=msg.sender, amount=msg.value)

@external
@view
def getDeposited() -> uint256:
    return self.deposited
"""


class TestFallbackRoundtrip:
    def test_fallback_compiles_without_inputs_outputs(self):
        abi = _compile_abi(FALLBACK_ONLY)
        assert abi == [{"stateMutability": "payable", "type": "fallback"}]

    def test_fallback_abi_from_json_abi(self):
        abi = _compile_abi(FALLBACK_ONLY)
        interface = InterfaceT.from_json_abi("FallbackContract", abi)
        # fallback is not a "function", so interface has no functions
        assert len(interface.functions) == 0


class TestConstructorRoundtrip:
    def test_constructor_abi_structure(self):
        abi = _compile_abi(CONSTRUCTOR_ONLY)
        assert abi == [
            {"inputs": [], "outputs": [], "stateMutability": "nonpayable", "type": "constructor"}
        ]

    def test_constructor_with_args_abi_structure(self):
        abi = _compile_abi(CONSTRUCTOR_WITH_ARGS)
        constructors = [e for e in abi if e["type"] == "constructor"]
        assert len(constructors) == 1
        assert constructors[0] == {
            "inputs": [{"name": "initial_owner", "type": "address"}],
            "outputs": [],
            "stateMutability": "nonpayable",
            "type": "constructor",
        }

    def test_constructor_from_json_abi(self):
        abi = _compile_abi(CONSTRUCTOR_ONLY)
        interface = InterfaceT.from_json_abi("CtorContract", abi)
        assert len(interface.functions) == 0


class TestSimpleFunctionRoundtrip:
    def test_compile_and_parse_back(self):
        abi = _compile_abi(SIMPLE_FUNCTION)
        assert abi == [
            {
                "name": "add",
                "inputs": [
                    {"name": "a", "type": "uint256"},
                    {"name": "b", "type": "uint256"},
                ],
                "outputs": [{"name": "", "type": "uint256"}],
                "stateMutability": "view",
                "type": "function",
            }
        ]

        fn = ContractFunctionT.from_abi(abi[0])
        assert fn.name == "add"
        assert len(fn.arguments) == 2
        assert fn.return_type is not None


class TestNoArgsNoReturnRoundtrip:
    def test_compile_and_parse_back(self):
        abi = _compile_abi(NO_ARGS_NO_RETURN)
        assert abi == [
            {
                "name": "ping",
                "inputs": [],
                "outputs": [],
                "stateMutability": "nonpayable",
                "type": "function",
            }
        ]

        fn = ContractFunctionT.from_abi(abi[0])
        assert fn.name == "ping"
        assert fn.arguments == []
        assert fn.return_type is None


class TestMultipleFunctionsAndEventsRoundtrip:
    def test_full_interface_roundtrip(self):
        abi = _compile_abi(MULTIPLE_FUNCTIONS_AND_EVENTS)
        interface = InterfaceT.from_json_abi("TokenLike", abi)

        assert set(interface.functions.keys()) == {"balanceOf", "transfer"}
        assert set(interface.events.keys()) == {"Transfer", "Approval"}

    def test_individual_function_roundtrip(self):
        abi = _compile_abi(MULTIPLE_FUNCTIONS_AND_EVENTS)
        func_entries = [e for e in abi if e.get("type") == "function"]

        for entry in func_entries:
            fn = ContractFunctionT.from_abi(entry)
            assert fn.name == entry["name"]
            assert len(fn.arguments) == len(entry["inputs"])

    def test_individual_event_roundtrip(self):
        abi = _compile_abi(MULTIPLE_FUNCTIONS_AND_EVENTS)
        event_entries = [e for e in abi if e.get("type") == "event"]

        for entry in event_entries:
            event = EventT.from_abi(entry)
            assert event.name == entry["name"]


class TestDefaultArgsRoundtrip:
    def test_expanded_entries_parse_back(self):
        abi = _compile_abi(DEFAULT_ARGS)
        func_entries = [e for e in abi if e.get("type") == "function"]
        # foo(a), foo(a,b), foo(a,b,c) = 3 entries
        assert len(func_entries) == 3

        for entry in func_entries:
            fn = ContractFunctionT.from_abi(entry)
            assert fn.name == "foo"
            assert fn.return_type is not None

    def test_deduplicated_entry_via_from_json_abi(self):
        abi = _compile_abi(DEFAULT_ARGS)
        # Default-arg expansion produces multiple entries with the same name.
        # from_json_abi rejects duplicate names, so we keep only the fullest
        # overload (most inputs) -- mirroring how external tools would
        # deduplicate before feeding ABI JSON back into Vyper.
        seen = {}
        for entry in abi:
            if entry.get("type") == "function":
                name = entry["name"]
                if name not in seen or len(entry["inputs"]) > len(seen[name]["inputs"]):
                    seen[name] = entry
        deduped_abi = list(seen.values())
        interface = InterfaceT.from_json_abi("DefaultArgs", deduped_abi)
        assert "foo" in interface.functions
        assert len(interface.functions["foo"].arguments) == 3


class TestPublicStateVarRoundtrip:
    def test_getter_roundtrip(self):
        abi = _compile_abi(PUBLIC_STATE_VAR)
        func_entries = [e for e in abi if e.get("type") == "function"]
        assert len(func_entries) == 2

        names = set()
        for entry in func_entries:
            fn = ContractFunctionT.from_abi(entry)
            names.add(fn.name)
            assert fn.arguments == []
            assert fn.return_type is not None
        assert names == {"totalSupply", "owner"}

    def test_getter_via_from_json_abi(self):
        abi = _compile_abi(PUBLIC_STATE_VAR)
        interface = InterfaceT.from_json_abi("PublicVars", abi)
        assert set(interface.functions.keys()) == {"totalSupply", "owner"}


class TestTupleReturnRoundtrip:
    def test_tuple_return_parse_back(self):
        abi = _compile_abi(TUPLE_RETURN)
        assert abi == [
            {
                "name": "getValues",
                "inputs": [],
                "outputs": [
                    {"name": "", "type": "uint256"},
                    {"name": "", "type": "address"},
                    {"name": "", "type": "bool"},
                ],
                "stateMutability": "view",
                "type": "function",
            }
        ]

        fn = ContractFunctionT.from_abi(abi[0])
        assert fn.name == "getValues"
        assert fn.return_type is not None


class TestMixedContractRoundtrip:
    def test_abi_contains_all_types(self):
        abi = _compile_abi(MIXED_CONTRACT)
        types_present = {entry.get("type") for entry in abi}
        assert "fallback" in types_present
        assert "constructor" in types_present
        assert "function" in types_present
        assert "event" in types_present

    def test_full_roundtrip_via_from_json_abi(self):
        abi = _compile_abi(MIXED_CONTRACT)
        interface = InterfaceT.from_json_abi("MixedContract", abi)
        assert "getDeposited" in interface.functions
        assert "deposited" in interface.functions
        assert "Deposit" in interface.events

    def test_each_function_entry_parses(self):
        abi = _compile_abi(MIXED_CONTRACT)
        func_entries = [e for e in abi if e.get("type") == "function"]
        for entry in func_entries:
            fn = ContractFunctionT.from_abi(entry)
            assert fn.name == entry["name"]

    def test_each_event_entry_parses(self):
        abi = _compile_abi(MIXED_CONTRACT)
        event_entries = [e for e in abi if e.get("type") == "event"]
        for entry in event_entries:
            event = EventT.from_abi(entry)
            assert event.name == entry["name"]

    def test_fallback_entry_structure(self):
        abi = _compile_abi(MIXED_CONTRACT)
        fallbacks = [e for e in abi if e.get("type") == "fallback"]
        assert len(fallbacks) == 1
        assert fallbacks[0] == {"stateMutability": "payable", "type": "fallback"}

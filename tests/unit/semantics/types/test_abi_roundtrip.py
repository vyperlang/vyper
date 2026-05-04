"""
Tests for ABI <-> Vyper type round-tripping.

Most tests in this file verify true round-trips: compile a Vyper contract to
ABI JSON, parse the entries back via ``ContractFunctionT.from_abi`` /
``EventT.from_abi`` / ``InterfaceT.from_json_abi``, re-serialize them with
``to_toplevel_abi_dict``, and assert the result equals the original ABI.

The ``TestFallbackABIHandling`` and ``TestConstructorABIHandling`` classes are
not round-trip tests: ``from_json_abi`` intentionally skips ``fallback`` and
``constructor`` entries, so they cannot be reconstructed back into Vyper
types. Those tests instead verify that such entries are emitted with the
correct shape (no ``inputs`` / ``outputs`` for fallback) and are skipped
without error by ``from_json_abi`` -- which is the behavior this PR fixes.
"""

import json

from vyper.compiler.output import build_abi_output
from vyper.compiler.phases import CompilerData
from vyper.semantics.types.function import ContractFunctionT
from vyper.semantics.types.module import InterfaceT
from vyper.semantics.types.user import EventT


def _compile_abi(source: str) -> list[dict]:
    data = CompilerData(source)
    return build_abi_output(data)


def _sorted_abi(entries: list[dict]) -> list[dict]:
    """Sort ABI entries deterministically for comparison."""
    return sorted(entries, key=lambda x: json.dumps(x, sort_keys=True))


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


class TestFallbackABIHandling:
    # Not a round-trip: fallback entries are skipped by from_json_abi.
    # These tests verify ABI shape and that from_json_abi handles them
    # without error (the behavior this PR fixes).
    def test_fallback_has_no_inputs_outputs(self):
        abi = _compile_abi(FALLBACK_ONLY)
        fallbacks = [e for e in abi if e.get("type") == "fallback"]
        assert len(fallbacks) == 1
        assert "inputs" not in fallbacks[0]
        assert "outputs" not in fallbacks[0]

    def test_fallback_skipped_by_from_json_abi(self):
        abi = _compile_abi(FALLBACK_ONLY)
        interface = InterfaceT.from_json_abi("FallbackContract", abi)
        assert len(interface.functions) == 0


class TestConstructorABIHandling:
    # Not a round-trip: constructor entries are skipped by from_json_abi.
    def test_constructor_skipped_by_from_json_abi(self):
        abi = _compile_abi(CONSTRUCTOR_ONLY)
        constructors = [e for e in abi if e["type"] == "constructor"]
        assert len(constructors) == 1

        interface = InterfaceT.from_json_abi("CtorContract", abi)
        assert len(interface.functions) == 0

    def test_constructor_with_args_skipped_by_from_json_abi(self):
        abi = _compile_abi(CONSTRUCTOR_WITH_ARGS)
        constructors = [e for e in abi if e["type"] == "constructor"]
        assert len(constructors) == 1
        assert len(constructors[0]["inputs"]) == 1

        interface = InterfaceT.from_json_abi("CtorArgsContract", abi)
        assert len(interface.functions) == 0


class TestSimpleFunctionRoundtrip:
    def test_function_abi_survives_roundtrip(self):
        abi = _compile_abi(SIMPLE_FUNCTION)
        assert len(abi) == 1
        fn = ContractFunctionT.from_abi(abi[0])
        reconstructed = fn.to_toplevel_abi_dict()
        assert reconstructed == [abi[0]]


class TestNoArgsNoReturnRoundtrip:
    def test_function_abi_survives_roundtrip(self):
        abi = _compile_abi(NO_ARGS_NO_RETURN)
        assert len(abi) == 1
        fn = ContractFunctionT.from_abi(abi[0])
        reconstructed = fn.to_toplevel_abi_dict()
        assert reconstructed == [abi[0]]


class TestMultipleFunctionsAndEventsRoundtrip:
    def test_interface_abi_survives_roundtrip(self):
        abi = _compile_abi(MULTIPLE_FUNCTIONS_AND_EVENTS)
        interface = InterfaceT.from_json_abi("TokenLike", abi)
        reconstructed = interface.to_toplevel_abi_dict()
        # from_json_abi only processes functions and events
        func_event_abi = [e for e in abi if e.get("type") in ("function", "event")]
        assert _sorted_abi(reconstructed) == _sorted_abi(func_event_abi)

    def test_individual_function_abi_survives_roundtrip(self):
        abi = _compile_abi(MULTIPLE_FUNCTIONS_AND_EVENTS)
        for entry in abi:
            if entry.get("type") == "function":
                fn = ContractFunctionT.from_abi(entry)
                assert fn.to_toplevel_abi_dict() == [entry]

    def test_individual_event_abi_survives_roundtrip(self):
        abi = _compile_abi(MULTIPLE_FUNCTIONS_AND_EVENTS)
        for entry in abi:
            if entry.get("type") == "event":
                event = EventT.from_abi(entry)
                assert event.to_toplevel_abi_dict() == [entry]


class TestPublicStateVarRoundtrip:
    def test_getter_abi_survives_roundtrip(self):
        abi = _compile_abi(PUBLIC_STATE_VAR)
        for entry in abi:
            fn = ContractFunctionT.from_abi(entry)
            assert fn.to_toplevel_abi_dict() == [entry]

    def test_getter_interface_abi_survives_roundtrip(self):
        abi = _compile_abi(PUBLIC_STATE_VAR)
        interface = InterfaceT.from_json_abi("PublicVars", abi)
        reconstructed = interface.to_toplevel_abi_dict()
        assert _sorted_abi(reconstructed) == _sorted_abi(abi)


class TestTupleReturnRoundtrip:
    def test_tuple_return_abi_survives_roundtrip(self):
        abi = _compile_abi(TUPLE_RETURN)
        assert len(abi) == 1
        fn = ContractFunctionT.from_abi(abi[0])
        assert fn.to_toplevel_abi_dict() == [abi[0]]


class TestMixedContractRoundtrip:
    def test_abi_contains_all_types(self):
        abi = _compile_abi(MIXED_CONTRACT)
        types_present = {entry.get("type") for entry in abi}
        assert types_present == {"fallback", "constructor", "function", "event"}

    def test_interface_abi_survives_roundtrip(self):
        abi = _compile_abi(MIXED_CONTRACT)
        interface = InterfaceT.from_json_abi("MixedContract", abi)
        reconstructed = interface.to_toplevel_abi_dict()
        # from_json_abi skips fallback and constructor entries
        func_event_abi = [e for e in abi if e.get("type") in ("function", "event")]
        assert _sorted_abi(reconstructed) == _sorted_abi(func_event_abi)

    def test_each_function_abi_survives_roundtrip(self):
        abi = _compile_abi(MIXED_CONTRACT)
        for entry in abi:
            if entry.get("type") == "function":
                fn = ContractFunctionT.from_abi(entry)
                assert fn.to_toplevel_abi_dict() == [entry]

    def test_each_event_abi_survives_roundtrip(self):
        abi = _compile_abi(MIXED_CONTRACT)
        for entry in abi:
            if entry.get("type") == "event":
                event = EventT.from_abi(entry)
                assert event.to_toplevel_abi_dict() == [entry]
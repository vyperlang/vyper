from collections import defaultdict
from dataclasses import dataclass, make_dataclass
from functools import cached_property
from os.path import basename
from typing import TYPE_CHECKING, Any, Optional, Union
from warnings import warn

from eth_typing import ChecksumAddress, HexAddress
from eth_utils import to_checksum_address

from vyper.semantics.analysis.base import FunctionVisibility, StateMutability
from vyper.utils import keccak256, method_id

from .abi import abi_decode, abi_encode, is_abi_encodable

if TYPE_CHECKING:
    from tests.evm_backends.base_env import BaseEnv, LogEntry


@dataclass
class ABILog:
    """Represents a parsed log entry from a contract."""

    address: ChecksumAddress
    args: tuple
    event: str
    topics: list[bytes]
    raw_data: bytes


class ABILogTopic:
    """Represents a log event topic in an ABI."""

    def __init__(self, event_abi: dict, contract_name: str):
        self._abi = event_abi
        self._contract_name = contract_name

    @cached_property
    def topic_id(self) -> bytes:
        """The keccak256 hash of the event signature."""
        if self._abi.get("anonymous") is True:
            return b""
        return keccak256((self.name + self.signature).encode())

    @property
    def name(self) -> str:
        return self._abi.get("name") or self._abi["type"]

    @property
    def indexed_inputs(self) -> list[dict]:
        return [item for item in self._abi["inputs"] if item["indexed"]]

    @property
    def unindexed_inputs(self) -> list[dict]:
        return [item for item in self._abi["inputs"] if not item["indexed"]]

    @cached_property
    def indexed_types(self) -> list[str]:
        return [_abi_from_json(i) for i in self.indexed_inputs]

    @cached_property
    def unindexed_types(self) -> list[str]:
        return [_abi_from_json(i) for i in self.unindexed_inputs]

    @property
    def signature(self) -> str:
        return f"({_format_abi_type(self.indexed_types + self.unindexed_types)})"

    def __repr__(self) -> str:
        return f"ABITopic {self._contract_name}.{self.signature} (0x{self.topic_id.hex()})"

    def parse(self, log: "LogEntry") -> ABILog:
        topics, raw_data = log.data
        return ABILog(
            address=to_checksum_address(log.address),
            args=self._parse_args(log),
            event=self.name,
            topics=topics,
            raw_data=raw_data,
        )

    @cached_property
    def data_type(self) -> type:
        """
        Create a dataclass for the log event data.
        """
        inputs = self.indexed_inputs + self.unindexed_inputs
        fields = [(item["name"], item["type"]) for item in inputs]
        return make_dataclass(self.name, fields)

    def _parse_args(self, log: "LogEntry") -> Any:
        """Convert the log data into a dataclass instance."""
        topics, data = log.data
        assert len(topics) == 1 + len(self.indexed_inputs), "Invalid log topic count"
        indexed = [
            t if self._is_hashed(typ) else abi_decode(f"{_format_abi_type([typ])}", t)
            for typ, t in zip(self.indexed_types, topics[1:])
        ]
        decoded = abi_decode(f"({_format_abi_type(self.unindexed_types)})", data)
        return self.data_type(*indexed, *decoded)

    @staticmethod
    def _is_hashed(typ):
        """Check if a type is hashed when included in a log topic."""
        return typ in ("bytes", "string", "tuple") or typ.endswith("[]")


class ABIFunction:
    """A single function in an ABI. It does not include overloads."""

    def __init__(self, abi: dict, contract_name: str):
        """
        :param abi: the ABI entry for this function
        :param contract_name: the name of the contract this function belongs to
        """
        self._abi = abi
        self._contract_name = contract_name
        self._function_visibility = FunctionVisibility.EXTERNAL
        self._mutability = StateMutability.from_abi(abi)
        self.contract: Optional["ABIContract"] = None

    @property
    def name(self) -> str:
        # note: the `constructor` definition does not have a name
        return self._abi.get("name") or self._abi["type"]

    @cached_property
    def argument_types(self) -> list:
        return [_abi_from_json(i) for i in self._abi["inputs"]]

    @property
    def argument_count(self) -> int:
        return len(self.argument_types)

    @property
    def _args_signature(self) -> str:
        return f"({_format_abi_type(self.argument_types)})"

    @cached_property
    def return_type(self) -> list:
        return [_abi_from_json(o) for o in self._abi["outputs"]]

    @property
    def full_signature(self) -> str:
        return f"{self.name}{self._args_signature}"

    @property
    def pretty_signature(self) -> str:
        return f"{self.name}{self._args_signature} -> {self.return_type}"

    @cached_property
    def method_id(self) -> bytes:
        if self._abi["type"] == "constructor":
            return b""  # constructors don't have method IDs
        return method_id(self.name + self._args_signature)

    def __repr__(self) -> str:
        return f"ABI {self._contract_name}.{self.pretty_signature}"

    def __str__(self) -> str:
        return repr(self)

    @property
    def is_mutable(self) -> bool:
        return self._mutability > StateMutability.VIEW

    def is_encodable(self, *args, **kwargs) -> bool:
        """Check whether this function accepts the given arguments after eventual encoding."""
        if len(kwargs) + len(args) != self.argument_count:
            return False
        parsed_args = self._merge_kwargs(*args, **kwargs)
        return all(
            is_abi_encodable(abi_type, arg)
            for abi_type, arg in zip(self.argument_types, parsed_args)
        )

    def prepare_calldata(self, *args, **kwargs) -> bytes:
        """Prepare the call data for the function call."""
        abi_args = self._merge_kwargs(*args, **kwargs)
        return self.method_id + abi_encode(self._args_signature, abi_args)

    def _merge_kwargs(self, *args, **kwargs) -> list:
        """Merge positional and keyword arguments into a single list."""
        if len(kwargs) + len(args) != self.argument_count:
            raise TypeError(
                "invocation failed due to improper number of arguments to"
                f" `{repr(self)}` (expected {self.argument_count} "
                f"arguments, got {len(args)} args and {len(kwargs)} kwargs)"
            )
        try:
            kwarg_inputs = self._abi["inputs"][len(args) :]
            return list(args) + [kwargs.pop(i["name"]) for i in kwarg_inputs]
        except KeyError as e:
            error = (
                f"Missing keyword argument {e} for `{self._args_signature}`. Passed {args} {kwargs}"
            )
            raise TypeError(error)

    def __call__(self, *args, value=0, gas=None, gas_price=0, sender=None, **kwargs):
        """Calls the function with the given arguments based on the ABI contract."""
        if not self.contract or not self.contract.env:
            raise Exception(f"Cannot call {self} without deploying contract.")

        if sender is None:
            sender = self.contract.env.deployer

        computation = self.contract.env.message_call(
            to=self.contract.address,
            sender=sender,
            data=self.prepare_calldata(*args, **kwargs),
            value=value,
            gas=gas,
            gas_price=gas_price,
            is_modifying=self.is_mutable,
        )

        match self.contract.marshal_to_python(computation, self.return_type):
            case ():
                return None
            case (single,):
                return single
            case multiple:
                return multiple


class ABIOverload:
    """
    Represents a set of functions that have the same name but different
    argument types. This is used to implement function overloading.
    """

    @staticmethod
    def create(
        functions: list[ABIFunction], contract: "ABIContract"
    ) -> Union["ABIOverload", ABIFunction]:
        """
        Create an ABIOverload if there are multiple functions, otherwise
        return the single function.
        :param functions: a list of functions with the same name
        :param contract: the ABIContract that these functions belong to
        """
        for f in functions:
            f.contract = contract
        if len(functions) == 1:
            return functions[0]
        return ABIOverload(functions)

    def __init__(self, functions: list[ABIFunction]):
        self.functions = functions

    @cached_property
    def name(self) -> str:
        return self.functions[0].name

    def __call__(
        self, *args, value=0, gas=None, sender=None, disambiguate_signature=None, **kwargs
    ):
        """
        Call the function that matches the given arguments.
        :raises Exception: if a single function is not found
        """
        function = self._pick_overload(
            *args, disambiguate_signature=disambiguate_signature, **kwargs
        )
        return function(*args, value=value, gas=gas, sender=sender, **kwargs)

    def _pick_overload(self, *args, disambiguate_signature=None, **kwargs) -> ABIFunction:
        """Pick the function that matches the given arguments."""
        if disambiguate_signature is None:
            matches = [f for f in self.functions if f.is_encodable(*args, **kwargs)]
        else:
            matches = [f for f in self.functions if disambiguate_signature == f.full_signature]
            assert len(matches) <= 1, "ABI signature must be unique"

        match matches:
            case [function]:
                return function
            case []:
                raise Exception(
                    f"Could not find matching {self.name} function for given arguments."
                )
            case multiple:
                raise Exception(
                    f"Ambiguous call to {self.name}. "
                    f"Arguments can be encoded to multiple overloads: "
                    f"{', '.join(self.name + f._args_signature for f in multiple)}. "
                    f"(Hint: try using `disambiguate_signature=` to disambiguate)."
                )


class ABIContract:
    """A contract that has been deployed to the blockchain and created via an ABI."""

    @property
    def address(self) -> HexAddress:
        assert self._address is not None
        return self._address

    def __init__(
        self,
        env: "BaseEnv",
        name: str,
        abi: dict,
        functions: list[ABIFunction],
        log_topics: list[ABILogTopic],
        bytecode: Optional[bytes],
        address: HexAddress,
        filename: Optional[str] = None,
    ):
        self.env = env
        self._address = address  # this can be overridden by subclasses
        self.filename = filename
        self.abi = abi
        self._name = name
        self._functions = functions
        self.log_topics = log_topics
        self.bytecode = bytecode
        self._deployed_bytecode = self.env.get_code(address)
        if not self._deployed_bytecode:
            warn(f"Requested {self} but there is no bytecode at that address!", stacklevel=2)

        overloads = defaultdict(list)
        for f in functions:
            overloads[f.name].append(f)

        for name, group in overloads.items():
            setattr(self, name, ABIOverload.create(group, self))

        self._address = address

    def marshal_to_python(self, result: bytes, abi_type: list[str]) -> list[Any]:
        """
        Convert the output of a contract call to a Python object.
        :param result: the computation result returned by `message_call`
        :param abi_type: the ABI type of the return value.
        """
        schema = f"({_format_abi_type(abi_type)})"
        return abi_decode(schema, result)

    def __repr__(self):
        file_str = f" (file {self.filename})" if self.filename else ""
        warn_str = "" if self._deployed_bytecode else " (WARNING: no bytecode at this address!)"
        return f"<{self._name} interface at {self.address}{warn_str}>{file_str}"

    def parse_log(self, log: "LogEntry") -> ABILog:
        """
        Parse a log entry into an ABILog object.
        :param log: the log entry to parse
        """
        topic_id_str = log.topics[0]
        topic_id = bytes.fromhex(topic_id_str.removeprefix("0x"))
        for topic in self.log_topics:
            if topic.topic_id == topic_id:
                return topic.parse(log)
        raise KeyError(f"Could not find event for log {topic_id_str}. Found {self.log_topics}")


class ABIContractFactory:
    """
    Represents an ABI contract that has not been coupled with an address yet.
    This is named `Factory` instead of `Deployer` because it doesn't actually
    do any contract deployment.
    """

    def __init__(
        self,
        name: str,
        abi: dict,
        functions: list[ABIFunction],
        log_topics: list[ABILogTopic],
        bytecode: Optional[bytes] = None,
    ):
        self._name = name
        self._abi = abi
        self._functions = functions
        self._log_topics = log_topics
        self._bytecode = bytecode

    @classmethod
    def from_abi_dict(cls, abi, name="<anonymous contract>", bytecode: Optional[bytes] = None):
        functions = [ABIFunction(item, name) for item in abi if item.get("type") == "function"]
        log_topics = [ABILogTopic(item, name) for item in abi if item.get("type") == "event"]
        return cls(basename(name), abi, functions, log_topics, bytecode)

    def at(self, env, address: HexAddress) -> ABIContract:
        """
        Create an ABI contract object for a deployed contract at `address`.
        """
        return ABIContract(
            env, self._name, self._abi, self._functions, self._log_topics, self._bytecode, address
        )


def _abi_from_json(abi: dict) -> str:
    """
    Parses an ABI type into its schema string.
    :param abi: The ABI type to parse.
    :return: The schema string for the given abi type.
    """
    if "components" in abi:
        components = ",".join([_abi_from_json(item) for item in abi["components"]])
        if abi["type"].startswith("tuple"):
            return f"({components}){abi['type'][5:]}"
        raise ValueError("Components found in non-tuple type " + abi["type"])

    return abi["type"]


def _format_abi_type(types: list) -> str:
    """
    Converts a list of ABI types into a comma-separated string.
    """
    return ",".join(
        item if isinstance(item, str) else f"({_format_abi_type(item)})" for item in types
    )

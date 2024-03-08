from collections import defaultdict
from functools import cached_property
from os.path import basename
from typing import TYPE_CHECKING, Any, Optional, Union
from warnings import warn

from eth_typing import HexAddress

from vyper.semantics.analysis.base import FunctionVisibility, StateMutability
from vyper.utils import method_id

from .abi import abi_decode, abi_encode, is_abi_encodable

if TYPE_CHECKING:
    from tests.revm.revm_env import RevmEnv


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
        return self._abi["name"]

    @cached_property
    def argument_types(self) -> list:
        return [_abi_from_json(i) for i in self._abi["inputs"]]

    @property
    def argument_count(self) -> int:
        return len(self.argument_types)

    @property
    def signature(self) -> str:
        return f"({_format_abi_type(self.argument_types)})"

    @cached_property
    def return_type(self) -> list:
        return [_abi_from_json(o) for o in self._abi["outputs"]]

    @property
    def full_signature(self) -> str:
        return f"{self.name}{self.signature}"

    @property
    def pretty_signature(self) -> str:
        return f"{self.name}{self.signature} -> {self.return_type}"

    @cached_property
    def method_id(self) -> bytes:
        return method_id(self.name + self.signature)

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

    def _merge_kwargs(self, *args, **kwargs) -> list:
        """Merge positional and keyword arguments into a single list."""
        if len(kwargs) + len(args) != self.argument_count:
            raise TypeError(
                f"Bad args to `{repr(self)}` (expected {self.argument_count} "
                f"arguments, got {len(args)} args and {len(kwargs)} kwargs)"
            )
        try:
            kwarg_inputs = self._abi["inputs"][len(args) :]
            return list(args) + [kwargs.pop(i["name"]) for i in kwarg_inputs]
        except KeyError as e:
            error = f"Missing keyword argument {e} for `{self.signature}`. Passed {args} {kwargs}"
            raise TypeError(error)

    def __call__(self, *args, value=0, gas=None, sender=None, transact=None, **kwargs):
        """Calls the function with the given arguments based on the ABI contract."""
        if not self.contract or not self.contract.env:
            raise Exception(f"Cannot call {self} without deploying contract.")

        if sender is None:
            sender = self.contract.env.deployer

        args = self._merge_kwargs(*args, **kwargs)
        computation = self.contract.env.execute_code(
            to_address=self.contract.address,
            sender=sender,
            data=self.method_id + abi_encode(self.signature, args),
            value=value,
            gas=gas,
            is_modifying=self.is_mutable,
            contract=self.contract,
            transact=transact,
        )

        match self.contract.marshal_to_python(computation, self.return_type):
            case ():
                return None
            case (single,):
                return single
            case multiple:
                return tuple(multiple)


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
        self,
        *args,
        value=0,
        gas=None,
        sender=None,
        disambiguate_signature=None,
        transact=None,
        **kwargs,
    ):
        """
        Call the function that matches the given arguments.
        :raises Exception: if a single function is not found
        """
        function = self._pick_overload(
            *args, disambiguate_signature=disambiguate_signature, **kwargs
        )
        return function(*args, value=value, gas=gas, sender=sender, transact=transact, **kwargs)

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
                    f"{', '.join(self.name + f.signature for f in multiple)}. "
                    f"(Hint: try using `disambiguate_signature=` to disambiguate)."
                )


class ABIContract:
    """A contract that has been deployed to the blockchain and created via an ABI."""

    @property
    def address(self) -> str:
        assert self._address is not None
        return self._address

    def __init__(
        self,
        env: "RevmEnv",
        name: str,
        abi: dict,
        functions: list[ABIFunction],
        address: HexAddress,
        filename: Optional[str] = None,
    ):
        self.env = env
        self._address = address  # this can be overridden by subclasses
        self.filename = filename
        self.abi = abi
        self._name = name
        self._functions = functions
        self._bytecode = self.env.get_code(address)
        if not self._bytecode:
            warn(
                f"Requested {self} but there is no bytecode at that address!",
                stacklevel=2,
            )

        overloads = defaultdict(list)
        for f in functions:
            overloads[f.name].append(f)

        for name, group in overloads.items():
            setattr(self, name, ABIOverload.create(group, self))

        self._address = address

    @cached_property
    def method_id_map(self):
        """
        Returns a mapping from method id to function object.
        This is used to create the stack trace when an error occurs.
        """
        return {function.method_id: function for function in self._functions}

    def marshal_to_python(self, result: bytes, abi_type: list[str]) -> tuple[Any, ...]:
        """
        Convert the output of a contract call to a Python object.
        :param result: the computation result returned by `execute_code`
        :param abi_type: the ABI type of the return value.
        """
        schema = f"({_format_abi_type(abi_type)})"
        return abi_decode(schema, result)

    @property
    def deployer(self) -> "ABIContractFactory":
        """
        Returns a factory that can be used to retrieve another deployed contract.
        """
        return ABIContractFactory(self._name, self.abi, self._functions)

    def __repr__(self):
        file_str = f" (file {self.filename})" if self.filename else ""
        warn_str = "" if self._bytecode else " (WARNING: no bytecode at this address!)"
        return f"<{self._name} interface at {self.address}{warn_str}>{file_str}"


class ABIContractFactory:
    """
    Represents an ABI contract that has not been coupled with an address yet.
    This is named `Factory` instead of `Deployer` because it doesn't actually
    do any contract deployment.
    """

    def __init__(
        self, name: str, abi: dict, functions: list["ABIFunction"], filename: Optional[str] = None
    ):
        self._name = name
        self._abi = abi
        self._functions = functions
        self._filename = filename

    @classmethod
    def from_abi_dict(cls, abi, name="<anonymous contract>"):
        functions = [ABIFunction(item, name) for item in abi if item.get("type") == "function"]
        return cls(basename(name), abi, functions, filename=name)

    def at(self, env, address: HexAddress) -> ABIContract:
        """
        Create an ABI contract object for a deployed contract at `address`.
        """
        contract = ABIContract(env, self._name, self._abi, self._functions, address, self._filename)
        env.register_contract(address, contract)
        return contract


def _abi_from_json(abi: dict) -> str:
    """
    Parses an ABI type into its schema string.
    :param abi: The ABI type to parse.
    :return: The schema string for the given abi type.
    """
    if "components" in abi:
        components = ",".join([_abi_from_json(item) for item in abi["components"]])
        if abi["type"] == "tuple":
            return f"({components})"
        if abi["type"] == "tuple[]":
            return f"({components})[]"
        raise ValueError("Components found in non-tuple type " + abi["type"])

    return abi["type"]


def _format_abi_type(types: list) -> str:
    """
    Converts a list of ABI types into a comma-separated string.
    """
    return ",".join(
        item if isinstance(item, str) else f"({_format_abi_type(item)})" for item in types
    )

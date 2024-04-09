import json
from collections import namedtuple
from contextlib import contextmanager
from typing import Callable

from eth_keys.datatypes import PrivateKey
from eth_utils import to_checksum_address

from tests.evm_backends.abi import abi_decode
from tests.evm_backends.abi_contract import ABIContract, ABIContractFactory, ABIFunction
from vyper.ast.grammar import parse_vyper_source
from vyper.compiler import CompilerData, Settings, compile_code
from vyper.utils import ERC5202_PREFIX, method_id

# a very simple log representation for the raw log entries
LogEntry = namedtuple("LogEntry", ["address", "topics", "data"])

# object returned by `last_result` property
ExecutionResult = namedtuple("ExecutionResult", ["is_success", "logs", "gas_refunded", "gas_used"])


class EvmError(RuntimeError):
    """Exception raised when a transaction reverts."""


class BaseEnv:
    """
    Base class for EVM backends.
    It provides a common interface for deploying contracts and interacting with them.
    """

    INVALID_OPCODE_ERROR = "NotImplemented"  # must be implemented by subclasses
    DEFAULT_CHAIN_ID = 1

    def __init__(self, gas_limit: int, account_keys: list[PrivateKey]) -> None:
        self.gas_limit = gas_limit
        self._keys = account_keys
        self.deployer: str = self._keys[0].public_key.to_checksum_address()

    @contextmanager
    def sender(self, address: str):
        original_deployer = self.deployer
        self.deployer = address
        try:
            yield
        finally:
            self.deployer = original_deployer

    def deploy(self, abi: list[dict], bytecode: bytes, value=0, *args, **kwargs):
        """Deploy a contract with the given ABI and bytecode."""
        factory = ABIContractFactory.from_abi_dict(abi, bytecode=bytecode)

        initcode = bytecode
        if args or kwargs:
            ctor_abi = next(i for i in abi if i["type"] == "constructor")
            ctor = ABIFunction(ctor_abi, contract_name=factory._name)
            initcode += ctor.prepare_calldata(*args, **kwargs)

        try:
            deployed_at = self._deploy(initcode, value)
        except RuntimeError as e:
            raise EvmError(*e.args) from e

        address = to_checksum_address(deployed_at)
        return factory.at(self, address)

    def deploy_source(
        self,
        source_code: str,
        output_formats: dict[str, Callable[[CompilerData], str]],
        compiler_settings: Settings,
        *args,
        input_bundle=None,
        **kwargs,
    ) -> ABIContract:
        """Compile and deploy a contract from source code."""
        abi, bytecode = _compile(source_code, output_formats, compiler_settings, input_bundle)
        value = (
            kwargs.pop("value", 0) or kwargs.pop("value_in_eth", 0) * 10**18
        )  # Handle deploying with an eth value.

        return self.deploy(abi, bytecode, value, *args, **kwargs)

    def deploy_blueprint(
        self,
        source_code,
        output_formats,
        compiler_settings: Settings,
        *args,
        input_bundle=None,
        initcode_prefix=ERC5202_PREFIX,
    ):
        """Deploy a contract with a blueprint pattern."""
        abi, bytecode = _compile(source_code, output_formats, compiler_settings, input_bundle)
        bytecode = initcode_prefix + bytecode
        bytecode_len = len(bytecode)
        bytecode_len_hex = hex(bytecode_len)[2:].rjust(4, "0")
        # prepend a quick deploy preamble
        deploy_preamble = bytes.fromhex("61" + bytecode_len_hex + "3d81600a3d39f3")
        deploy_bytecode = deploy_preamble + bytecode

        deployer_abi: list[dict] = []  # just a constructor
        value = 0
        deployer = self.deploy(deployer_abi, deploy_bytecode, value, *args)

        def factory(address):
            return ABIContractFactory.from_abi_dict(abi).at(self, address)

        return deployer, factory

    def get_logs(self, contract: ABIContract, event_name: str = None, raw=False):
        logs = [log for log in self.last_result.logs if contract.address == log.address]
        if raw:
            return [log.data for log in logs]

        parsed_logs = [contract.parse_log(log) for log in logs]
        if event_name:
            return [log for log in parsed_logs if log.event == event_name]

        return parsed_logs

    @contextmanager
    def anchor(self):
        raise NotImplementedError  # must be implemented by subclasses

    def get_balance(self, address: str) -> int:
        raise NotImplementedError  # must be implemented by subclasses

    def set_balance(self, address: str, value: int):
        raise NotImplementedError  # must be implemented by subclasses

    @property
    def accounts(self) -> list[str]:
        raise NotImplementedError  # must be implemented by subclasses

    @property
    def block_number(self) -> int:
        raise NotImplementedError  # must be implemented by subclasses

    @property
    def timestamp(self) -> int | None:
        raise NotImplementedError  # must be implemented by subclasses

    @property
    def last_result(self) -> ExecutionResult:
        raise NotImplementedError  # must be implemented by subclasses

    def execute_code(
        self,
        to: str,
        sender: str | None = None,
        data: bytes | str = b"",
        value: int = 0,
        gas: int | None = None,
        gas_price: int = 0,
        is_modifying: bool = True,
    ) -> bytes:
        raise NotImplementedError  # must be implemented by subclasses

    def get_code(self, address: str) -> bytes:
        raise NotImplementedError  # must be implemented by subclasses

    def time_travel(self, num_blocks=1, time_delta: int | None = None) -> None:
        raise NotImplementedError  # must be implemented by subclasses

    def _deploy(self, code: bytes, value: int, gas: int | None = None) -> str:
        raise NotImplementedError  # must be implemented by subclasses

    @staticmethod
    def _parse_revert(output_bytes: bytes, error: Exception, gas_used: int):
        """
        Tries to parse the EIP-838 revert reason from the output bytes.
        """
        # REVIEW: not sure the prefix is needed
        prefix = "execution reverted"
        if output_bytes[:4] == method_id("Error(string)"):
            (msg,) = abi_decode("(string)", output_bytes[4:])
            raise EvmError(f"{prefix}: {msg}", gas_used) from error

        raise EvmError(f"{prefix}: 0x{output_bytes.hex()}", gas_used) from error


def _compile(
    source_code: str,
    output_formats: dict[str, Callable[[CompilerData], str]],
    settings: Settings,
    input_bundle=None,
) -> tuple[list[dict], bytes]:
    out = compile_code(
        source_code,
        # test that all output formats can get generated
        output_formats=output_formats,
        settings=settings,
        input_bundle=input_bundle,
        show_gas_estimates=True,  # Enable gas estimates for testing
    )
    parse_vyper_source(source_code)  # Test grammar.
    json.dumps(out["metadata"])  # test metadata is json serializable
    return out["abi"], bytes.fromhex(out["bytecode"].removeprefix("0x"))

import json
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Callable, Optional

from eth_keys.datatypes import PrivateKey
from eth_utils import to_checksum_address

from tests.evm_backends.abi import abi_decode
from tests.evm_backends.abi_contract import ABIContract, ABIContractFactory, ABIFunction
from vyper.ast.grammar import parse_vyper_source
from vyper.compiler import CompilerData, InputBundle, Settings, compile_code
from vyper.utils import ERC5202_PREFIX, method_id


# a very simple log representation for the raw log entries
@dataclass
class LogEntry:
    address: str
    topics: list[str]
    data: tuple[list[bytes], bytes]  # (topic list, non-topic)


# object returned by `last_result` property
@dataclass
class ExecutionResult:
    is_success: bool
    logs: list[LogEntry]
    gas_refunded: int
    gas_used: int


class EvmError(RuntimeError):
    """Exception raised when a call fails."""


class ExecutionReverted(EvmError):
    """Exception raised when a call reverts."""


class BaseEnv:
    """
    Base class for EVM backends.
    It provides a common interface for deploying contracts and interacting with them.
    """

    DEFAULT_CHAIN_ID = 1

    def __init__(self, gas_limit: int, account_keys: list[PrivateKey]) -> None:
        self.gas_limit = gas_limit
        self._keys = account_keys
        self.deployer: str = self._keys[0].public_key.to_checksum_address()

    def deploy(self, abi: list[dict], bytecode: bytes, value=0, *args, **kwargs):
        """Deploy a contract with the given ABI and bytecode."""
        factory = ABIContractFactory.from_abi_dict(abi, bytecode=bytecode)

        initcode = bytecode
        if args or kwargs:
            ctor_abi = next(i for i in abi if i["type"] == "constructor")
            ctor = ABIFunction(ctor_abi, contract_name=factory._name)
            initcode += ctor.prepare_calldata(*args, **kwargs)

        deployed_at = self._deploy(initcode, value)
        address = to_checksum_address(deployed_at)
        return factory.at(self, address)

    def deploy_source(
        self,
        source_code: str,
        output_formats: dict[str, Callable[[CompilerData], str]],
        *args,
        compiler_settings: Settings = None,
        input_bundle: InputBundle = None,
        value: int = 0,
        **kwargs,
    ) -> ABIContract:
        """Compile and deploy a contract from source code."""
        abi, bytecode = _compile(source_code, output_formats, input_bundle, compiler_settings)
        return self.deploy(abi, bytecode, value, *args, **kwargs)

    def deploy_blueprint(
        self,
        source_code,
        output_formats,
        *args,
        input_bundle: InputBundle = None,
        initcode_prefix: bytes = ERC5202_PREFIX,
    ):
        """Deploy a contract with a blueprint pattern."""
        abi, bytecode = _compile(source_code, output_formats, input_bundle)
        bytecode = initcode_prefix + bytecode
        bytecode_len = len(bytecode)
        bytecode_len_hex = hex(bytecode_len)[2:].rjust(4, "0")
        # prepend a quick deploy preamble
        deploy_preamble = bytes.fromhex("61" + bytecode_len_hex + "3d81600a3d39f3")
        deploy_bytecode = deploy_preamble + bytecode

        deployer_abi: list[dict] = []  # just a constructor
        deployer = self.deploy(deployer_abi, deploy_bytecode, *args)

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

    @property
    def accounts(self) -> list[str]:
        return [key.public_key.to_checksum_address() for key in self._keys]

    @contextmanager
    def anchor(self):
        raise NotImplementedError  # must be implemented by subclasses

    def get_balance(self, address: str) -> int:
        raise NotImplementedError  # must be implemented by subclasses

    def set_balance(self, address: str, value: int):
        raise NotImplementedError  # must be implemented by subclasses

    @property
    def block_number(self) -> int:
        raise NotImplementedError  # must be implemented by subclasses

    @block_number.setter
    def block_number(self, value: int):
        raise NotImplementedError

    @property
    def timestamp(self) -> int | None:
        raise NotImplementedError  # must be implemented by subclasses

    @timestamp.setter
    def timestamp(self, value: int):
        raise NotImplementedError  # must be implemented by subclasses

    @property
    def last_result(self) -> ExecutionResult:
        raise NotImplementedError  # must be implemented by subclasses

    @property
    def blob_hashes(self) -> list[bytes]:
        raise NotImplementedError  # must be implemented by subclasses

    @blob_hashes.setter
    def blob_hashes(self, value: list[bytes]):
        raise NotImplementedError  # must be implemented by subclasses

    def message_call(
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

    def clear_transient_storage(self) -> None:
        raise NotImplementedError  # must be implemented by subclasses

    def get_code(self, address: str) -> bytes:
        raise NotImplementedError  # must be implemented by subclasses

    def get_excess_blob_gas(self) -> Optional[int]:
        raise NotImplementedError  # must be implemented by subclasses

    def set_excess_blob_gas(self, param):
        raise NotImplementedError  # must be implemented by subclasses

    def _deploy(self, code: bytes, value: int, gas: int | None = None) -> str:
        raise NotImplementedError  # must be implemented by subclasses

    @staticmethod
    def _parse_revert(output_bytes: bytes, error: Exception, gas_used: int):
        """
        Tries to parse the EIP-838 revert reason from the output bytes.
        """
        if output_bytes[:4] == method_id("Error(string)"):
            (msg,) = abi_decode("(string)", output_bytes[4:])
            raise ExecutionReverted(f"{msg}", gas_used) from error

        raise ExecutionReverted(f"0x{output_bytes.hex()}", gas_used) from error

    @property
    def invalid_opcode_error(self) -> str:
        """Expected error message when invalid opcode is executed."""
        raise NotImplementedError  # must be implemented by subclasses

    @property
    def out_of_gas_error(self) -> str:
        """Expected error message when user runs out of gas"""
        raise NotImplementedError  # must be implemented by subclasses


def _compile(
    source_code: str,
    output_formats: dict[str, Callable[[CompilerData], str]],
    input_bundle: InputBundle = None,
    settings: Settings = None,
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

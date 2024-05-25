import copy
import logging
from contextlib import contextmanager
from typing import Optional

import rlp
from cached_property import cached_property
from eth.abc import ChainAPI, ComputationAPI, VirtualMachineAPI
from eth.chains.mainnet import MainnetChain
from eth.constants import CREATE_CONTRACT_ADDRESS, GENESIS_DIFFICULTY
from eth.db.atomic import AtomicDB
from eth.exceptions import Revert, VMError
from eth.tools.builder import chain as chain_builder
from eth.vm.base import StateAPI
from eth.vm.execution_context import ExecutionContext
from eth.vm.forks.cancun.transaction_context import CancunTransactionContext
from eth.vm.message import Message
from eth_keys.datatypes import PrivateKey
from eth_typing import Address
from eth_utils import setup_DEBUG2_logging, to_canonical_address, to_checksum_address

import vyper.evm.opcodes as evm_opcodes
from tests.evm_backends.base_env import BaseEnv, EvmError, ExecutionResult, LogEntry
from vyper.utils import keccak256


class PyEvmEnv(BaseEnv):
    """EVM backend environment using the Py-EVM library."""

    invalid_opcode_error = "Invalid opcode"
    out_of_gas_error = "Out of gas"

    def __init__(
        self,
        gas_limit: int,
        account_keys: list[PrivateKey],
        tracing: bool,
        block_number: int,
        evm_version: str,
    ) -> None:
        super().__init__(gas_limit, account_keys)

        evm_opcodes.DEFAULT_EVM_VERSION = evm_version

        if tracing:
            logger = logging.getLogger("eth.vm.computation.BaseComputation")
            setup_DEBUG2_logging()
            logger.setLevel("DEBUG2")
            # from vdb import vdb
            # vdb.set_evm_opcode_debugger()

        spec = getattr(chain_builder, evm_version + "_at")(block_number)
        self._chain: ChainAPI = chain_builder.build(MainnetChain, spec).from_genesis(
            base_db=AtomicDB(),
            genesis_params={"difficulty": GENESIS_DIFFICULTY, "gas_limit": gas_limit},
        )

        self._last_computation: ComputationAPI = None
        self._blob_hashes: list[bytes] = []

    @cached_property
    def _state(self) -> StateAPI:
        return self._vm.state

    @cached_property
    def _vm(self) -> VirtualMachineAPI:
        return self._chain.get_vm()

    @property
    def _context(self) -> ExecutionContext:
        context = self._state.execution_context
        assert isinstance(context, ExecutionContext)  # help mypy
        return context

    @contextmanager
    def anchor(self):
        snapshot_id = self._state.snapshot()
        ctx = copy.copy(self._state.execution_context)
        try:
            yield
        finally:
            self._state.revert(snapshot_id)
            self._state.execution_context = ctx

    def get_balance(self, address: str) -> int:
        return self._state.get_balance(_addr(address))

    def set_balance(self, address: str, value: int):
        self._state.set_balance(_addr(address), value)

    @property
    def block_number(self) -> int:
        return self._context.block_number

    @block_number.setter
    def block_number(self, value: int):
        self._context._block_number = value

    @property
    def timestamp(self) -> int | None:
        return self._context.timestamp

    @timestamp.setter
    def timestamp(self, value: int):
        self._context._timestamp = value

    @property
    def last_result(self) -> ExecutionResult:
        result = self._last_computation
        return ExecutionResult(
            is_success=not result.is_error,
            logs=list(_parse_log_entries(result)),
            gas_refunded=result.get_gas_refund(),
            gas_used=result.get_gas_used(),
        )

    @property
    def blob_hashes(self) -> list[bytes]:
        return self._blob_hashes

    @blob_hashes.setter
    def blob_hashes(self, value: list[bytes]):
        self._blob_hashes = value

    def message_call(
        self,
        to: str,
        sender: str | None = None,
        data: bytes | str = b"",
        value: int = 0,
        gas: int | None = None,
        gas_price: int = 0,
        is_modifying: bool = True,
    ):
        if isinstance(data, str):
            data = bytes.fromhex(data.removeprefix("0x"))
        sender = _addr(sender or self.deployer)
        try:
            computation = self._state.computation_class.apply_message(
                state=self._state,
                message=Message(
                    to=_addr(to),
                    sender=sender,
                    data=data,
                    code=self.get_code(to),
                    value=value,
                    gas=self.gas_limit if gas is None else gas,
                    is_static=not is_modifying,
                ),
                transaction_context=self._make_tx_context(sender, gas_price),
            )
        except VMError as e:
            # py-evm raises when user is out-of-funds instead of returning a failed computation
            raise EvmError(*e.args) from e

        self._check_computation(computation)
        return computation.output

    def _make_tx_context(self, sender, gas_price):
        context_class = self._state.transaction_context_class
        context = context_class(origin=sender, gas_price=gas_price)
        if self._blob_hashes:
            assert isinstance(context, CancunTransactionContext)
            context._blob_versioned_hashes = self._blob_hashes
        return context

    def clear_transient_storage(self) -> None:
        try:
            self._state.clear_transient_storage()
        except AttributeError as e:
            assert e.args == ("No transient_storage has been set for this State",)

    def _check_computation(self, computation):
        self._last_computation = computation
        if computation.is_error:
            if isinstance(computation.error, Revert):
                (output,) = computation.error.args
                gas_used = computation.get_gas_used()
                self._parse_revert(output, computation.error, gas_used)

            raise EvmError(*computation.error.args) from computation.error

    def get_code(self, address: str):
        return self._state.get_code(_addr(address))

    def get_excess_blob_gas(self) -> Optional[int]:
        return self._context.excess_blob_gas

    def set_excess_blob_gas(self, param):
        self._context._excess_blob_gas = param

    def _deploy(self, code: bytes, value: int, gas: int = None) -> str:
        sender = _addr(self.deployer)
        target_address = self._generate_contract_address(sender)

        try:
            computation = self._state.computation_class.apply_create_message(
                state=self._state,
                message=Message(
                    to=CREATE_CONTRACT_ADDRESS,  # i.e., b""
                    sender=sender,
                    value=value,
                    code=code,
                    data=b"",
                    gas=gas or self.gas_limit,
                    create_address=target_address,
                ),
                transaction_context=self._make_tx_context(sender, gas_price=0),
            )
        except VMError as e:
            # py-evm raises when user is out-of-funds instead of returning a failed computation
            raise EvmError(*e.args) from e

        self._check_computation(computation)
        return "0x" + target_address.hex()

    def _generate_contract_address(self, sender: Address) -> Address:
        nonce = self._state.get_nonce(sender)
        self._state.increment_nonce(sender)
        next_account_hash = keccak256(rlp.encode([sender, nonce]))
        return to_canonical_address(next_account_hash[-20:])


def _parse_log_entries(result: ComputationAPI):
    """
    Parses the raw log entries from a computation result into a more
    usable format similar to the revm backend.
    """
    for address, topics, data in result.get_log_entries():
        topic_bytes = [t.to_bytes(32, "big") for t in topics]
        topic_ids = ["0x" + t.hex() for t in topic_bytes]
        yield LogEntry(to_checksum_address(address), topic_ids, (topic_bytes, data))


def _addr(address: str) -> Address:
    """Convert an address string to an Address object."""
    return Address(bytes.fromhex(address.removeprefix("0x")))

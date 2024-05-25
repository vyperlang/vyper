import re
from contextlib import contextmanager
from typing import Optional

from eth_keys.datatypes import PrivateKey
from pyrevm import EVM, BlockEnv, Env

from tests.evm_backends.base_env import BaseEnv, EvmError, ExecutionResult


class RevmEnv(BaseEnv):
    invalid_opcode_error = "InvalidFEOpcode"
    out_of_gas_error = "OutOfGas"

    def __init__(
        self,
        gas_limit: int,
        account_keys: list[PrivateKey],
        tracing: bool,
        block_number: int,
        evm_version: str,
    ) -> None:
        super().__init__(gas_limit, account_keys)
        self._evm = EVM(
            gas_limit=gas_limit,
            tracing=tracing,
            spec_id=evm_version,
            env=Env(block=BlockEnv(number=block_number)),
        )

    @contextmanager
    def anchor(self):
        snapshot_id = self._evm.snapshot()
        block = BlockEnv(number=self._evm.env.block.number, timestamp=self._evm.env.block.timestamp)
        try:
            yield
        finally:
            try:
                self._evm.revert(snapshot_id)
            except OverflowError:
                # snapshot_id is reverted by the transaction already.
                # revm updates are needed to make the journal more robust.
                pass
            self._evm.set_block_env(block)
            # self._evm.set_tx_env(tx)

    def get_balance(self, address: str) -> int:
        return self._evm.get_balance(address)

    def set_balance(self, address: str, value: int):
        self._evm.set_balance(address, value)

    @property
    def block_number(self) -> int:
        return self._evm.env.block.number

    @block_number.setter
    def block_number(self, value: int):
        block = self._evm.env.block
        block.number = value
        self._evm.set_block_env(block)

    @property
    def timestamp(self) -> int | None:
        return self._evm.env.block.timestamp

    @timestamp.setter
    def timestamp(self, value: int):
        block = self._evm.env.block
        block.timestamp = value
        self._evm.set_block_env(block)

    @property
    def last_result(self) -> ExecutionResult:
        result = self._evm.result
        return ExecutionResult(
            gas_refunded=result.gas_refunded,
            gas_used=result.gas_used,
            is_success=result.is_success,
            logs=result.logs,
        )

    @property
    def blob_hashes(self):
        return self._evm.env.tx.blob_hashes

    @blob_hashes.setter
    def blob_hashes(self, value):
        tx = self._evm.env.tx
        tx.blob_hashes = value
        self._evm.set_tx_env(tx)

    def message_call(
        self,
        to: str,
        sender: str | None = None,
        data: bytes | str = b"",
        value: int = 0,
        gas: int | None = None,
        gas_price: int = 0,
        is_modifying: bool = True,
        blob_hashes: Optional[list[bytes]] = None,  # for blobbasefee >= Cancun
    ):
        if isinstance(data, str):
            data = bytes.fromhex(data.removeprefix("0x"))

        try:
            return self._evm.message_call(
                to=to,
                caller=sender or self.deployer,
                calldata=data,
                value=value,
                gas=self.gas_limit if gas is None else gas,
                gas_price=gas_price,
                is_static=not is_modifying,
            )
        except RuntimeError as e:
            self._parse_error(e)
            raise EvmError(*e.args) from e

    def clear_transient_storage(self) -> None:
        self._evm.reset_transient_storage()

    def get_code(self, address: str):
        return self._evm.basic(address).code.rstrip(b"\0")

    def get_excess_blob_gas(self) -> Optional[int]:
        return self._evm.env.block.excess_blob_gas

    def get_blob_gasprice(self) -> Optional[int]:
        return self._evm.env.block.blob_gasprice

    def set_excess_blob_gas(self, value):
        self._evm.env.block.excess_blob_gas = value

    def _deploy(self, code: bytes, value: int, gas: int = None) -> str:
        try:
            return self._evm.deploy(self.deployer, code, value, gas)
        except RuntimeError as e:
            self._parse_error(e)
            raise EvmError(*e.args) from e

    def _parse_error(self, e: RuntimeError):
        # TODO: Create a custom error in pyrevm instead parsing strings
        if match := re.match(r"Revert \{ gas_used: (\d+), output: 0x([0-9a-f]*) }", e.args[0]):
            gas_used, output_str = match.groups()
            output_bytes = bytes.fromhex(output_str)
            super()._parse_revert(output_bytes, e, int(gas_used))

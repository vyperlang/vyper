import re
from contextlib import contextmanager

from eth_keys.datatypes import PrivateKey
from pyrevm import EVM, BlockEnv, Env

from tests.evm_backends.base_env import BaseEnv, EvmError, ExecutionResult


class RevmEnv(BaseEnv):
    INVALID_OPCODE_ERROR = "InvalidFEOpcode"

    def __init__(
        self,
        gas_limit: int,
        account_keys: list[PrivateKey],
        tracing=False,
        block_number=1,
        evm_version="latest",
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
        try:
            yield
        finally:
            try:
                self._evm.revert(snapshot_id)
            except OverflowError:
                # snapshot_id is reverted by the transaction already.
                # revm updates are needed to make the journal more robust.
                pass

    def get_balance(self, address: str) -> int:
        return self._evm.get_balance(address)

    def set_balance(self, address: str, value: int):
        self._evm.set_balance(address, value)

    @property
    def accounts(self) -> list[str]:
        return [key.public_key.to_checksum_address() for key in self._keys]

    @property
    def block_number(self) -> int:
        return self._evm.env.block.number

    @property
    def timestamp(self) -> int | None:
        return self._evm.env.block.timestamp

    @property
    def last_result(self) -> ExecutionResult:
        result = self._evm.result
        return ExecutionResult(
            gas_refunded=result.gas_refunded,
            gas_used=result.gas_used,
            is_success=result.is_success,
            logs=result.logs,
        )

    def execute_code(
        self,
        to: str,
        sender: str | None = None,
        data: bytes | str = b"",
        value: int = 0,
        gas: int | None = None,
        gas_price: int = 0,
        is_modifying: bool = True,
    ):
        data = data if isinstance(data, bytes) else bytes.fromhex(data.removeprefix("0x"))
        try:
            output = self._evm.message_call(
                to=to,
                caller=sender or self.deployer,
                calldata=data,
                value=value,
                gas=self.gas_limit if gas is None else gas,
                gas_price=gas_price,
                is_static=not is_modifying,
            )
            return bytes(output)
        except RuntimeError as e:
            if match := re.match(r"Revert \{ gas_used: (\d+), output: 0x([0-9a-f]+) }", e.args[0]):
                gas_used, output_str = match.groups()
                output_bytes = bytes.fromhex(output_str)
                self._parse_revert(output_bytes, e, int(gas_used))
            raise EvmError(*e.args) from e
        finally:
            # clear transient storage after every call, since we are not committing anything
            self._evm.reset_transient_storage()

    def get_code(self, address: str):
        return self._evm.basic(address).code.rstrip(b"\0")

    def time_travel(self, num_blocks=1, time_delta: int | None = None) -> None:
        """
        Move the block number forward by `num_blocks` and the timestamp forward by `time_delta`.
        """
        if time_delta is None:
            time_delta = num_blocks
        block = self._evm.env.block
        self._evm.set_block_env(
            BlockEnv(
                number=block.number + num_blocks,
                coinbase=block.coinbase,
                timestamp=block.timestamp + time_delta,
                difficulty=block.difficulty,
                prevrandao=block.prevrandao,
                basefee=block.basefee,
                gas_limit=block.gas_limit,
                excess_blob_gas=block.excess_blob_gas,
            )
        )

    def _deploy(self, code: bytes, value: int, gas: int = None) -> str:
        try:
            return self._evm.deploy(self.deployer, code, value, gas)
        finally:
            # clear transient storage after every call, since we are not committing anything
            self._evm.reset_transient_storage()

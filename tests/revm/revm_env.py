import json
import re
from contextlib import contextmanager
from typing import Callable, Tuple

from eth_keys.datatypes import PrivateKey
from eth_tester.backends.pyevm.main import get_default_account_keys
from eth_tester.exceptions import TransactionFailed
from eth_typing import HexAddress
from eth_utils import to_checksum_address
from hexbytes import HexBytes
from pyrevm import EVM, BlockEnv, Env

from tests.revm.abi import abi_decode, abi_encode
from tests.revm.abi_contract import ABIContract, ABIContractFactory, ABIFunction
from vyper.ast.grammar import parse_vyper_source
from vyper.compiler import CompilerData, Settings, compile_code
from vyper.compiler.settings import OptimizationLevel
from vyper.utils import ERC5202_PREFIX, method_id


class RevmEnv:
    default_chain_id = 1

    def __init__(self, gas_limit: int, tracing=False, block_number=1, evm_version="latest") -> None:
        self.gas_limit = gas_limit
        self.evm = EVM(
            gas_limit=gas_limit,
            tracing=tracing,
            spec_id=evm_version,
            env=Env(block=BlockEnv(number=block_number)),
        )
        self.contracts: dict[HexAddress, ABIContract] = {}
        self._keys: list[PrivateKey] = get_default_account_keys()
        self.deployer = self._keys[0].public_key.to_checksum_address()

    @contextmanager
    def anchor(self):
        snapshot_id = self.evm.snapshot()
        try:
            yield
        finally:
            self.evm.revert(snapshot_id)

    @contextmanager
    def sender(self, address: HexAddress):
        original_deployer = self.deployer
        self.deployer = address
        try:
            yield
        finally:
            self.deployer = original_deployer

    def get_balance(self, address: HexAddress) -> int:
        return self.evm.get_balance(address)

    def set_balance(self, address: HexAddress, value: int):
        self.evm.set_balance(address, value)

    @property
    def accounts(self) -> list[HexAddress]:
        return [key.public_key.to_checksum_address() for key in self._keys]

    @property
    def block_number(self) -> int:
        return self.evm.env.block.number

    def get_block(self, _=None) -> BlockEnv:
        return self.evm.env.block

    def contract(self, abi, bytecode) -> "ABIContract":
        return ABIContractFactory.from_abi_dict(abi).at(self, bytecode)

    def execute_code(
        self,
        to: HexAddress,
        sender: HexAddress | None = None,
        data: bytes | str = b"",
        value: int | None = None,
        gas: int | None = None,
        is_modifying: bool = True,
        # TODO: Remove the following. They are not used.
        transact: dict | None = None,
        contract=None,
    ):
        transact = transact or {}
        data = data if isinstance(data, bytes) else bytes.fromhex(data.removeprefix("0x"))
        try:
            output = self.evm.message_call(
                to=to,
                caller=transact.get("from", sender) or self.deployer,
                calldata=data,
                value=transact.get("value", value),
                gas=transact.get("gas", gas) or self.gas_limit,
                gas_price=transact.get("gasPrice"),
                is_static=not is_modifying,
            )
            return bytes(output)
        except RuntimeError as e:
            if match := re.match(r"Revert \{ gas_used: (\d+), output: 0x([0-9a-f]+) }", e.args[0]):
                gas_used, output_str = match.groups()
                output_bytes = bytes.fromhex(output_str)
                # Check EIP838 error, with ABI Error(string)
                if output_bytes[:4] == method_id("Error(string)"):
                    (msg,) = abi_decode("(string)", output_bytes[4:])
                    raise TransactionFailed(f"execution reverted: {msg}", gas_used) from e
            raise TransactionFailed(*e.args) from e

    def get_code(self, address: HexAddress):
        return HexBytes(self.evm.basic(address).code.rstrip(b"\0"))

    def register_contract(self, address: HexAddress, contract: "ABIContract"):
        self.contracts[address] = contract

    def deploy_source(
        self,
        source_code: str,
        optimize: OptimizationLevel,
        output_formats: dict[str, Callable[[CompilerData], str]],
        *args,
        override_opt_level=None,
        input_bundle=None,
        evm_version=None,
        **kwargs,
    ) -> ABIContract:
        abi, bytecode = self._compile(
            source_code, optimize, output_formats, override_opt_level, input_bundle, evm_version
        )
        value = (
            kwargs.pop("value", 0) or kwargs.pop("value_in_eth", 0) * 10**18
        )  # Handle deploying with an eth value.

        return self.deploy(abi, bytecode, value, *args, **kwargs)

    def _compile(
        self, source_code, optimize, output_formats, override_opt_level, input_bundle, evm_version
    ) -> Tuple[list[dict], HexBytes]:
        out = compile_code(
            source_code,
            # test that all output formats can get generated
            output_formats=output_formats,
            settings=Settings(evm_version=evm_version, optimize=override_opt_level or optimize),
            input_bundle=input_bundle,
            show_gas_estimates=True,  # Enable gas estimates for testing
        )
        parse_vyper_source(source_code)  # Test grammar.
        json.dumps(out["metadata"])  # test metadata is json serializable
        return out["abi"], HexBytes(out["bytecode"])

    def deploy_blueprint(
        self,
        source_code,
        optimize,
        output_formats,
        *args,
        override_opt_level=None,
        input_bundle=None,
        evm_version=None,
        initcode_prefix=ERC5202_PREFIX,
    ):
        abi, bytecode = self._compile(
            source_code, optimize, output_formats, override_opt_level, input_bundle, evm_version
        )
        bytecode = HexBytes(initcode_prefix + bytecode)
        bytecode_len = len(bytecode)
        bytecode_len_hex = hex(bytecode_len)[2:].rjust(4, "0")
        # prepend a quick deploy preamble
        deploy_preamble = HexBytes("61" + bytecode_len_hex + "3d81600a3d39f3")
        deploy_bytecode = deploy_preamble + bytecode

        deployer_abi = []  # just a constructor
        value = 0
        deployer = self.deploy(deployer_abi, deploy_bytecode, value, *args)

        def factory(address):
            return ABIContractFactory.from_abi_dict(abi).at(self, address)

        return deployer, factory

    def deploy(self, abi: list[dict], bytecode: bytes, value=0, *args, **kwargs):
        factory = ABIContractFactory.from_abi_dict(abi, bytecode=bytecode)

        initcode = bytecode
        if args or kwargs:
            ctor_abi = next(i for i in abi if i["type"] == "constructor")
            ctor = ABIFunction(ctor_abi, contract_name=factory._name)
            initcode += abi_encode(ctor.signature, ctor._merge_kwargs(*args, **kwargs))

        try:
            deployed_at = self.evm.deploy(
                deployer=self.deployer, code=initcode, value=value, _abi=json.dumps(abi)
            )
        except RuntimeError as e:
            raise TransactionFailed(*e.args) from e

        address = to_checksum_address(deployed_at)
        return factory.at(self, address)

    def mine(self, num_blocks=1, time_delta: int | None = None) -> None:
        if time_delta is None:
            time_delta = num_blocks
        self.evm.set_block_env(
            BlockEnv(
                number=self.evm.env.block.number + num_blocks,
                coinbase=self.evm.env.block.coinbase,
                timestamp=self.evm.env.block.timestamp + time_delta,
                difficulty=self.evm.env.block.difficulty,
                prevrandao=self.evm.env.block.prevrandao,
                basefee=self.evm.env.block.basefee,
                gas_limit=self.evm.env.block.gas_limit,
                excess_blob_gas=self.evm.env.block.excess_blob_gas,
            )
        )

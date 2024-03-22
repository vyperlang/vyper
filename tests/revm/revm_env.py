import json
from typing import Callable, Tuple

from eth_keys.datatypes import PrivateKey
from eth_tester.backends.pyevm.main import get_default_account_keys
from eth_tester.exceptions import TransactionFailed
from eth_typing import HexAddress
from eth_utils import to_checksum_address
from hexbytes import HexBytes
from pyrevm import EVM

from tests.revm.abi import abi_encode
from tests.revm.abi_contract import ABIContract, ABIContractFactory, ABIFunction
from vyper.ast.grammar import parse_vyper_source
from vyper.compiler import CompilerData, Settings, compile_code
from vyper.compiler.settings import OptimizationLevel
from vyper.utils import ERC5202_PREFIX


class RevmEnv:
    def __init__(self, gas_limit: int, tracing=False) -> None:
        self.evm = EVM(gas_limit=gas_limit, tracing=tracing)
        self.contracts: dict[HexAddress, ABIContract] = {}
        self._keys: list[PrivateKey] = get_default_account_keys()

    @property
    def accounts(self) -> list[HexAddress]:
        return [k.public_key.to_checksum_address() for k in self._keys]

    @property
    def deployer(self) -> HexAddress:
        return self._keys[0].public_key.to_checksum_address()

    def set_balance(self, address: HexAddress, value: int):
        self.evm.set_balance(address, value)

    def contract(self, abi, bytecode) -> "ABIContract":
        return ABIContractFactory.from_abi_dict(abi).at(self, bytecode)

    def execute_code(
        self,
        to_address: HexAddress,
        sender: HexAddress,
        data: bytes | None,
        value: int | None = None,
        gas: int = 0,
        is_modifying: bool = True,
        # TODO: Remove the following. They are not used.
        transact=None,
        contract=None,
    ):
        try:
            output = self.evm.message_call(
                to=to_address,
                caller=sender,
                calldata=data,
                value=value,
                gas=gas,
                is_static=not is_modifying,
            )
            return bytes(output)
        except RuntimeError as e:
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
        deployer = self.deploy(deployer_abi, deploy_bytecode, value=0, *args)

        def factory(address):
            return ABIContractFactory.from_abi_dict(abi).at(self, address)

        return deployer, factory

    def deploy(self, abi: list[dict], bytecode: bytes, value=0, *args, **kwargs):
        factory = ABIContractFactory.from_abi_dict(abi=abi)

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

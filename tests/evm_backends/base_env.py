import json
from typing import Callable, Tuple

from eth_keys.datatypes import PrivateKey
from eth_tester.exceptions import TransactionFailed
from eth_utils import to_checksum_address

from tests.evm_backends.abi import abi_decode, abi_encode
from tests.evm_backends.abi_contract import ABIContract, ABIContractFactory, ABIFunction
from vyper.ast.grammar import parse_vyper_source
from vyper.compiler import CompilerData, Settings, compile_code
from vyper.compiler.settings import OptimizationLevel
from vyper.utils import ERC5202_PREFIX, method_id


class BaseEnv:
    default_chain_id = 1

    def __init__(self, gas_limit: int, account_keys: list[PrivateKey]) -> None:
        self.gas_limit = gas_limit
        self._keys = account_keys
        self.deployer: str = self._keys[0].public_key.to_checksum_address()

    def _deploy(self, initcode: bytes, value: int, gas: int = None) -> str:
        raise NotImplementedError

    def deploy(self, abi: list[dict], bytecode: bytes, value=0, *args, **kwargs):
        factory = ABIContractFactory.from_abi_dict(abi, bytecode=bytecode)

        initcode = bytecode
        if args or kwargs:
            ctor_abi = next(i for i in abi if i["type"] == "constructor")
            ctor = ABIFunction(ctor_abi, contract_name=factory._name)
            initcode += abi_encode(ctor.signature, ctor._merge_kwargs(*args, **kwargs))

        try:
            deployed_at = self._deploy(initcode, value)
        except RuntimeError as e:
            raise TransactionFailed(*e.args) from e

        address = to_checksum_address(deployed_at)
        return factory.at(self, address)

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
    ) -> Tuple[list[dict], bytes]:
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
        return out["abi"], bytes.fromhex(out["bytecode"].removeprefix("0x"))

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
        bytecode = bytes.fromhex(initcode_prefix + bytecode)
        bytecode_len = len(bytecode)
        bytecode_len_hex = hex(bytecode_len)[2:].rjust(4, "0")
        # prepend a quick deploy preamble
        deploy_preamble = bytes.fromhex("61" + bytecode_len_hex + "3d81600a3d39f3")
        deploy_bytecode = deploy_preamble + bytecode

        deployer_abi = []  # just a constructor
        value = 0
        deployer = self.deploy(deployer_abi, deploy_bytecode, value, *args)

        def factory(address):
            return ABIContractFactory.from_abi_dict(abi).at(self, address)

        return deployer, factory

    def _parse_revert(self, output_bytes, error, gas_used):
        # Check EIP838 error, with ABI Error(string)
        prefix = "execution reverted"
        if output_bytes[:4] == method_id("Error(string)"):
            (msg,) = abi_decode("(string)", output_bytes[4:])
            raise TransactionFailed(f"{prefix}: {msg}", gas_used) from error

        raise TransactionFailed(f"{prefix}: 0x{output_bytes.hex()}", gas_used) from error

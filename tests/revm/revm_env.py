import json
from typing import Callable

from eth_keys.datatypes import PrivateKey
from eth_tester.backends.pyevm.main import get_default_account_keys
from eth_tester.exceptions import TransactionFailed
from eth_typing import HexAddress
from eth_utils import to_checksum_address
from pyrevm import EVM, Env

from tests.revm.abi import abi_encode
from tests.revm.abi_contract import ABIContract, ABIContractFactory, ABIFunction
from vyper.ast.grammar import parse_vyper_source
from vyper.compiler import CompilerData, Settings, compile_code
from vyper.compiler.settings import OptimizationLevel


class RevmEnv:
    def __init__(self, gas_limit: int) -> None:
        self.env = Env()
        self.evm = EVM(env=self.env, gas_limit=gas_limit)
        self.bytecode: dict[HexAddress, str] = {}
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

    def execute_code(
        self,
        to_address: HexAddress,
        sender: HexAddress,
        data: list[int] | None,
        value: int | None,
        gas: int,
        is_modifying: bool,
        contract: "ABIContract",
        transact=None,
    ):
        try:
            fn = self.evm.call_raw_committing if transact is None else self.evm.call_raw
            output = fn(
                to=to_address,
                caller=sender,
                data=data,
                value=value,
                # gas=gas,
                # is_modifying=self.is_mutable,
                # contract=self.contract,
            )
            return bytes(output)
        except RuntimeError as e:
            (cause,) = e.args
            assert cause in ("Revert", "OutOfGas"), f"Unexpected error {e}"
            raise TransactionFailed(cause)

    def get_code(self, address: HexAddress):
        return self.bytecode[address]

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
        **kwargs,
    ) -> ABIContract:
        out = compile_code(
            source_code,
            # test that all output formats can get generated
            output_formats=output_formats,
            settings=Settings(
                evm_version=kwargs.pop("evm_version", None), optimize=override_opt_level or optimize
            ),
            input_bundle=input_bundle,
            show_gas_estimates=True,  # Enable gas estimates for testing
        )

        parse_vyper_source(source_code)  # Test grammar.
        json.dumps(out["metadata"])  # test metadata is json serializable

        abi = out["abi"]
        bytecode = out["bytecode"]
        value = (
            kwargs.pop("value", 0) or kwargs.pop("value_in_eth", 0) * 10**18
        )  # Handle deploying with an eth value.

        return self.deploy(abi, bytecode, value, *args, **kwargs)

    def deploy(self, abi: list[dict], bytecode: str, value: int, *args, **kwargs):
        factory = ABIContractFactory.from_abi_dict(abi=abi)

        initcode = bytes.fromhex(bytecode[2:])
        if args or kwargs:
            ctor_abi = next(i for i in abi if i["type"] == "constructor")
            ctor = ABIFunction(ctor_abi, contract_name=factory._name)
            initcode += abi_encode(ctor.signature, ctor._merge_kwargs(*args, **kwargs))

        deployed_at = self.evm.deploy(
            deployer=self.deployer,
            code=list(initcode),
            value=value,
            _abi=json.dumps(abi),
        )
        address = to_checksum_address(deployed_at)
        self.bytecode[address] = bytecode

        abi_contract = factory.at(self, address)

        return abi_contract

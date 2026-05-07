from vyper.semantics.types.function import ContractFunctionT
from vyper.semantics.types.module import InterfaceT
from vyper.semantics.types.user import EventT


class TestContractFunctionFromAbi:
    def test_missing_inputs(self):
        """Function ABI with missing 'inputs' key should not raise KeyError."""
        abi = {
            "name": "foo",
            "type": "function",
            "outputs": [{"name": "", "type": "uint256"}],
            "stateMutability": "view",
        }
        fn = ContractFunctionT.from_abi(abi)
        assert fn.name == "foo"
        assert fn.arguments == []

    def test_missing_outputs(self):
        """Function ABI with missing 'outputs' key should not raise KeyError."""
        abi = {
            "name": "bar",
            "type": "function",
            "inputs": [{"name": "x", "type": "uint256"}],
            "stateMutability": "nonpayable",
        }
        fn = ContractFunctionT.from_abi(abi)
        assert fn.name == "bar"
        assert fn.return_type is None

    def test_missing_both(self):
        """Function ABI with neither 'inputs' nor 'outputs' should not raise KeyError."""
        abi = {
            "name": "baz",
            "type": "function",
            "stateMutability": "nonpayable",
        }
        fn = ContractFunctionT.from_abi(abi)
        assert fn.name == "baz"
        assert fn.arguments == []
        assert fn.return_type is None


class TestEventFromAbi:
    def test_missing_inputs(self):
        """Event ABI with missing 'inputs' key should not raise KeyError."""
        abi = {
            "name": "Transfer",
            "type": "event",
        }
        event = EventT.from_abi(abi)
        assert event.name == "Transfer"


class TestInterfaceFromAbi:
    def test_function_missing_inputs_outputs(self):
        """InterfaceT.from_abi should handle functions with missing keys."""
        abi = [
            {
                "name": "noargs",
                "type": "function",
                "stateMutability": "view",
            },
            {
                "name": "Deposit",
                "type": "event",
            },
        ]
        interface = InterfaceT.from_json_abi("TestInterface", abi)
        assert interface is not None

## How to run  
- `pytest -n <NUM_PROCESSES> --export <EXPORT_PATH> <TEST_PATH>[::TEST_NAME] `  
  - <NUM_PROCESSES> – Number of processes to use (e.g., 1).   
    - *currently not parallelized -> must use 1 process (override the repo default `-n auto`)*  
  - <EXPORT_PATH> – Directory to save export results (e.g., tests/export).  
  - <TEST_PATH> – Path to the test file or directory (e.g., tests/functional/codegen/modules/test_exports.py).  
  - ::TEST_NAME – (Optional) Specific test function to run (e.g., test_simple_export).  
- example:  
  - `pytest -s -n 1 --export tests/export -m "not fuzzing" tests/functional/codegen/modules/test_exports.py::test_simple_export`  
  
## Format  
  
The exported data is organized into JSON files that mirror the test directory structure. Each JSON file contains test items (tests and fixtures) from the corresponding test module.  
  
### JSON Structure:  
  
```json  
{
  "test_or_fixture_name": {
    "item_type": "test" | "fixture",
    "deps": [
      "path/to/dependency1.json/fixture_name",
      "path/to/dependency2.json/fixture_name__2"
    ],
    "traces": [
      {
        "trace_type": "deployment",
        "deployment_type": "source" | "ir" | "blueprint" | "raw_bytecode",
        "function_name": "constructor",
        "python_args": {"args": [...], "kwargs": {...}},
        "contract_abi": [...],
        "initcode": "0x...",
        "calldata": "0x..." | null,
        "value": <uint>,
        "source_code": "contract code..." | null,
        "annotated_ast": {...} | null,
        "solc_json": {...} | null,
        "raw_ir": "IR representation" | null,
        "blueprint_initcode_prefix": "0x..." | null,
        "deployed_address": "0x...",
        "runtime_bytecode": "0x...",
        "deployment_succeeded": <bool>,
        "env": {
          "tx": {
            "origin": "0x...",
            "gas": <uint>,
            "gas_price": <uint>,
            "blob_hashes": ["0x..."]
          },
          "block": {
            "number": <uint>,
            "timestamp": <uint>,
            "gas_limit": <uint>,
            "excess_blob_gas": <uint> | null,
            "blob_basefee": <uint> | null,
            "block_hashes": {"<block_number>": "0x..."}
          }
        }
      },
      {
        "trace_type": "call",
        "output": "0x..." | null,
        "function_name": "foo" | null,
        "python_args": {"args": [...], "kwargs": {...}},
        "call_args": {
          "to": "0x...",
          "calldata": "0x...",
          "value": <uint>,
          "is_modifying": <bool>
        },
        "call_succeeded": <bool>,
        "env": {
          "tx": {
            "origin": "0x...",
            "gas": <uint>,
            "gas_price": <uint>,
            "blob_hashes": ["0x..."]
          },
          "block": {
            "number": <uint>,
            "timestamp": <uint>,
            "gas_limit": <uint>,
            "excess_blob_gas": <uint> | null,
            "blob_basefee": <uint> | null,
            "block_hashes": {"<block_number>": "0x..."}
          }
        }
      },
      {
        "trace_type": "set_balance",
        "address": "0x...",
        "value": <uint>
      },
      {
        "trace_type": "clear_transient_storage"
      }
    ]
  }
}
```  
- test items have their dependencies listed in the order in which they must be executed (note that dependencies can have further dependencies)
- example of dependency `"tests/export/functional/examples/tokens/test_erc20.json/c_origin"`
  - thus traces from the item `c_origin` at `test_erc20.json` must be executed first
- traces are listed in the order in which they must be executed
- a trace can be one of: "deployment", "call", "set_balance", or "clear_transient_storage"
- addresses are dumped as strings, bytes are hex encoded and dumped as strings
- `initcode` is `concat(bytecode, abi_encode(ctor_args))`
- `calldata` is `abi_encode(ctor_args)`
- `source_code` is the source of the compilation target, imported modules are accessible from `solc_json`
- `deployment_type` denotes how the contract was deployed
  - this was added because some tests deploy directly from `ir` or from directly from `bytecode`
- `env` field contains transaction and block environment data:
  - `tx.origin` is the transaction origin
  - `tx.gas` is the gas limit for the transaction
  - `tx.gas_price` is the gas price for the transaction
  - `tx.blob_hashes` is a list of blob hashes (hex encoded) for EIP-4844 transactions
  - `block.number` is the current block number
  - `block.timestamp` is the current block timestamp
  - `block.gas_limit` is the block gas limit
  - `block.excess_blob_gas` is the excess blob gas for EIP-4844 (can be null)
  - `block.blob_basefee` is the blob base fee calculated from excess blob gas (can be null)
  - `block.block_hashes` is a mapping of block numbers to their hashes (up to 256 previous blocks)
- `set_balance` traces capture direct balance modifications to accounts (useful for test setup)
- `clear_transient_storage` traces capture when transient storage is cleared between calls
  - this was added because a test runs in 1 global transcation context and all calls within the test are run as `message_calls`
  - as such, transient storage isn't clear after a call (nor are nonces increased etc.)

  
## How it works  
  
The test export feature provides a way to capture and export all contract deployments and function calls that occur during test execution.   
  
The exports might not capture all side-effects which executed during the test run if those aren't requested by the test author.  
  
### Key Components:  
  
1. **TestExporter** (`tests/exports.py`): The main class that manages the export process  
   - Tracks test items (tests and fixtures) with their dependencies (e.g. a test depends on a deployment from a fixture)  
   - Records deployment and call traces chronologically (the test execution is 1:1 replicable)  
   - Handles fixture deduplication (when fixtures are cached/reused)  
   - Organizes output by test file structure  
  
2. **Integration with pytest**:   
   - Hooks into pytest's fixture setup and test execution lifecycle (`pytest_runtest_call`, and `pytest_fixture_setup`)  
   - Tracks which fixtures are executed vs cached  
   - Maintains dependency relationships between tests and fixtures

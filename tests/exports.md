  
## How to run  
- `pytest -n <NUM_PROCESSES> --export <EXPORT_PATH> <TEST_PATH>[::TEST_NAME] `  
  - <NUM_PROCESSES> – Number of processes to use (e.g., 1).   
    - *currently not parallelized -> must use 1 process*  
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
        "deployer": "0x...",
        "deployment_type": "source" | "ir" | "blueprint" | "raw_bytecode",
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
        "deployment_succeeded": <bool>
      },
      {
        "trace_type": "call",
        "output": "0x..." | null,
        "call_args": {
          "to": "0x...",
          "sender": "0x...",
          "calldata": "0x...",
          "value": <uint>,
          "gas": <uint>,
          "gas_price": <uint>,
          "is_modifying": <bool>
        },
        "call_succeeded": <bool>
      }
    ]
  }
}
```  
- test items have their dependencies listed in the order in which they must be executed  
- a trace can be either a "call" or a "deployment"  
- addresses are dumped as strings, bytes are hex encoded and dumped as strings  
  
## How it works  
  
The test export feature provides a way to capture and export all contract deployments and function calls that occur during test execution.   
  
The exports might not capture all side-effects which executed during the test run.  
  
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
import unittest
from test import erc20_tests_1
from test import erc20_tests_2


def prettyprint(message):
    print("~" * 80, "\n" + message, "\n" + "~" * 80)


success = True

# Run first test suite (Phil Daian) on each contract
prettyprint("Running Solidity-compatible ERC20 tests, Suite 1")
res = unittest.TextTestRunner(verbosity=2).run(unittest.TestLoader().loadTestsFromModule(erc20_tests_1))
success &= res.wasSuccessful()
prettyprint("Finished Solidity-compatible ERC20 tests, Suite 1")

# Run second test suite (Florian Tramer) on each contract
prettyprint("Running Solidity-compatible ERC20 tests, Suite 2")
res = unittest.TextTestRunner(verbosity=2).run(unittest.TestLoader().loadTestsFromModule(erc20_tests_2))
success &= res.wasSuccessful()
prettyprint("Finished Solidity-compatible ERC20 tests, Suite 2")

if not success:
    print("FAILED : Test failures encounting, exiting with error.")
    exit(1)
else:
    print("All tests completed successfully.")

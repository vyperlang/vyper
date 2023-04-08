from vyper.semantics.types.primitives import SINT, UINT, BytesM_T, IntegerT

# shortcut type names
UINT256_T = IntegerT(False, 256)
UINT8_T = IntegerT(False, 8)
INT256_T = IntegerT(True, 256)
INT128_T = IntegerT(True, 128)
UINT160_T = IntegerT(False, 160)

BYTES32_T = BytesM_T(32)
BYTES20_T = BytesM_T(20)
BYTES4_T = BytesM_T(4)

_ = UINT, SINT  # explicitly use: addresses linter F401

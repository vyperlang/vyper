import pytest

from vyper.evm.assembler import assembly_to_evm
from vyper.venom.parser import parse_venom
from vyper.venom.resolve_const import resolve_const_operands
from vyper.venom.venom_to_assembly import VenomCompiler


def test_runtime_size_storage_deployment(env):
    """This test demonstrates an InvalidJump error that occurs with certain Venom code structures.
    """
    venom_code = """
const RUNTIME_SIZE = sub(@runtime_end, @runtime)

function __global {
  __global:
      invoke @constructor_StorageTest
      %runtime_size = @RUNTIME_SIZE
      %runtime_offset = @runtime
      codecopy 0, %runtime_offset, %runtime_size
      return 0, %runtime_size

  revert: [pinned]
      revert 0, 0
}  ; close function __global

function constructor_StorageTest {
  constructor_StorageTest:
      %1 = param
      sstore 0, 42
      ret %1
}  ; close function constructor_StorageTest

function runtime {
  runtime: [pinned]
      %1 = calldatasize
      %2 = iszero %1
      jnz %2, @1_then, @2_join

  1_then:
      %3 = sload 0
      %value = %3
      mstore 0, %value
      return 0, 32

  2_join:
      revert 0, 0
}  ; close function runtime

function runtime_end {
  runtime_end: [pinned]
      db x""
}  ; close function runtime_end
"""

    ctx = parse_venom(venom_code)
    
    resolve_const_operands(ctx)
    
    compiler = VenomCompiler(ctx)
    assembly = compiler.generate_evm_assembly(no_optimize=True)
    
    bytecode, _ = assembly_to_evm(assembly)

    deployed_contract = env.deploy(abi=[], bytecode=bytecode)
import pytest

from vyper.compiler.phases import generate_bytecode
from vyper.compiler.settings import OptimizationLevel, VenomOptimizationFlags
from vyper.venom import generate_assembly_experimental, run_passes_on
from vyper.venom.analysis import IRAnalysesCache
from vyper.venom.context import IRContext
from vyper.venom.parser import parse_venom
from vyper.venom.passes import SingleUseExpansion


def test_duplicate_operands():
    """
    Test the duplicate operands code generation.
    The venom code:

    %1 = 10
    %2 = add %1, %1
    %3 = mul %1, %2
    stop

    Should compile to: [PUSH1, 10, DUP1, DUP2, ADD, MUL, STOP]
    """
    ctx = IRContext()
    fn = ctx.create_function("test")
    bb = fn.get_basic_block()
    op = bb.append_instruction("assign", 10)
    sum_ = bb.append_instruction("add", op, op)
    bb.append_instruction("mul", sum_, op)
    bb.append_instruction("stop")

    ac = IRAnalysesCache(fn)
    SingleUseExpansion(ac, fn).run_pass()

    optimize = OptimizationLevel.GAS
    asm = generate_assembly_experimental(ctx, optimize=optimize)
    assert asm == ["PUSH1", 10, "DUP1", "DUP2", "ADD", "MUL", "STOP"]


def _deploy_runtime(env, runtime_bytecode):
    bytecode_len_hex = hex(len(runtime_bytecode))[2:].rjust(6, "0")
    initcode = bytes.fromhex("62" + bytecode_len_hex + "3d81600b3d39f3") + runtime_bytecode
    return env.deploy([], initcode)


def _word(value):
    return int(value).to_bytes(32, "big")


def test_phi_duplicate_incoming_operands(env):
    source = """
function runtime {
entry:
  %cond = calldataload 0
  %a = calldataload 32
  %b = calldataload 64
  %c = calldataload 96
  jnz %cond, @p1, @p2
p1:
  jmp @join
p2:
  jmp @join
join:
  %x = phi @p1, %a, @p2, %b
  %y = phi @p1, %a, @p2, %c
  %z = add %x, %y
  mstore 0, %z
  return 0, 32
}
    """

    ctx = parse_venom(source)
    run_passes_on(ctx, VenomOptimizationFlags(level=OptimizationLevel.GAS), disable_mem_checks=True)

    asm = generate_assembly_experimental(ctx, optimize=OptimizationLevel.GAS)
    runtime_bytecode, _ = generate_bytecode(asm)
    contract = _deploy_runtime(env, runtime_bytecode)

    calldata = b"".join(_word(x) for x in (1, 5, 7, 11))
    assert int.from_bytes(env.message_call(contract.address, data=calldata), "big") == 10

    calldata = b"".join(_word(x) for x in (0, 5, 7, 11))
    assert int.from_bytes(env.message_call(contract.address, data=calldata), "big") == 18


@pytest.mark.parametrize("cond", [0, 1])
@pytest.mark.parametrize("cond2", [0, 1])
def test_phi_operand_used_after_join(env, cond, cond2):
    # %a flows into the phi and is also used in a successor of the join
    source = """
function runtime {
entry:
  %cond = calldataload 0
  %a = calldataload 32
  %b = calldataload 64
  %cond2 = calldataload 96
  jnz %cond, @p1, @p2
p1:
  jmp @join
p2:
  jmp @join
join:
  %x = phi @p1, %a, @p2, %b
  jnz %cond2, @c1, @c2
c1:
  %z = add %x, %a
  mstore 0, %z
  return 0, 32
c2:
  mstore 0, %x
  return 0, 32
}
    """

    ctx = parse_venom(source)
    run_passes_on(ctx, VenomOptimizationFlags(level=OptimizationLevel.GAS), disable_mem_checks=True)

    asm = generate_assembly_experimental(ctx, optimize=OptimizationLevel.GAS)
    runtime_bytecode, _ = generate_bytecode(asm)
    contract = _deploy_runtime(env, runtime_bytecode)

    a, b = 5, 7
    calldata = b"".join(_word(x) for x in (cond, a, b, cond2))
    x = a if cond else b
    expected = x + a if cond2 else x
    assert int.from_bytes(env.message_call(contract.address, data=calldata), "big") == expected

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


def test_phi_dead_output(env):
    # a phi whose output is dead still needs its incoming value materialized
    # on the predecessor stack, otherwise codegen sees an empty stack at the
    # join. a live phi (`%live`) shares the join to check it is not corrupted.
    # codegen runs without optimization passes so the dead phi is not DCE'd.
    source = """
function runtime {
entry:
  %cond = calldataload 0
  %a = calldataload 32
  %b = calldataload 64
  %c = calldataload 96
  %d = calldataload 128
  jnz %cond, @p1, @p2
p1:
  jmp @join
p2:
  jmp @join
join:
  %dead = phi @p1, %a, @p2, %b
  %live = phi @p1, %c, @p2, %d
  mstore 0, %live
  return 0, 32
}
    """

    ctx = parse_venom(source)
    asm = generate_assembly_experimental(ctx, optimize=OptimizationLevel.GAS)
    runtime_bytecode, _ = generate_bytecode(asm)
    contract = _deploy_runtime(env, runtime_bytecode)

    calldata = b"".join(_word(x) for x in (1, 5, 7, 9, 11))  # cond=1 -> %live=%c=9
    assert int.from_bytes(env.message_call(contract.address, data=calldata), "big") == 9

    calldata = b"".join(_word(x) for x in (0, 5, 7, 9, 11))  # cond=0 -> %live=%d=11
    assert int.from_bytes(env.message_call(contract.address, data=calldata), "big") == 11

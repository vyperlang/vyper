from vyper.compiler.phases import generate_bytecode
from vyper.compiler.settings import OptimizationLevel
from vyper.venom import generate_assembly_experimental, run_passes_on
from vyper.venom.check_venom import check_venom_ctx
from vyper.venom.parser import parse_venom


def test_labels_as_variables():
    code = """
    function global {
      global:
        mstore 64, 128
        %2 = callvalue
        %3 = iszero %2
        jnz %3, @block_0xe, @block_0xb
      block_0xe:
        %6 = calldatasize
        %7 = lt %6, 4
        jnz %7, @block_0x2f, @block_0x17
      block_0xb:
        revert 0, 0
      block_0x2f:
        revert 0, 0
      block_0x17:
        %12 = calldataload 0
        %14 = shr 224, %12
        %16 = eq 10773267, %14
        jnz %16, @block_0x33, @block_0x25
      block_0x33:
        %block_57 = @block_0x39
        jmp @block_0x67
      block_0x25:
        %21 = eq 4171824493, %14
        jnz %21, @block_0x4d, @block_0x2f
      block_0x67:
        %phi0 = phi @block_0x33, %block_57, @block_0x6f, %block_118
        djmp %phi0, @block_0x76, @block_0x39
      block_0x4d:
        jmp @block_0x6f
      block_0x39:
        %28 = mload 64
        %block_68 = @block_0x44
        jmp @block_0x91
      block_0x6f:
        %block_118 = @block_0x76
        jmp @block_0x67
      block_0x91:
        %phi1 = phi @block_0x39, %28, @block_0x53, %45
        %phi2 = phi @block_0x39, %28, @block_0x53, %45
        %phi3 = phi @block_0x39, %block_68, @block_0x53, %block_94
        %36 = add %phi1, 32
        %39 = add %phi2, 0
        jmp @block_0x84
      block_0x84:
        jmp @block_0x7b
      block_0x76:
        jmp @block_0x53
      block_0x7b:
        jmp @block_0x8b
      block_0x53:
        %45 = mload 64
        %block_94 = @block_0x5e
        jmp @block_0x91
      block_0x8b:
        mstore %39, 1
        jmp @block_0xa2
      block_0xa2:
        djmp %phi3, @block_0x5e, @block_0x44
      block_0x44:
        %49 = mload 64
        %50 = sub %36, %49
        return %49, %50
      block_0x5e:
        %52 = mload 64
        %53 = sub %36, %52
        return %52, %53
    }
    """
    ctx = parse_venom(code)

    check_venom_ctx(ctx)

    run_passes_on(ctx, OptimizationLevel.default())
    asm = generate_assembly_experimental(ctx)
    generate_bytecode(asm, compiler_metadata=None)

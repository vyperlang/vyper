from vyper.venom.parser import parse_venom
from vyper.venom.venom_to_assembly import VenomCompiler


def test_dead_params():
    code = """
    function foo {
        main:
            %1 = param  ; dead
            %2 = param
            ret %2
    }
    """
    ctx = parse_venom(code)

    asm = VenomCompiler(ctx).generate_evm_assembly()
    assert asm == ["SWAP1", "POP", "JUMP"]


def test_optimistic_swap_params():
    code = """
    function foo {
        main:
            %1 = param
            %2 = param  ; %2 is scheduled before %3
            %3 = param
            %4 = 117  ; show that %2 gets swapped "optimistically" before this instruction
            mstore %1
            mstore %2
            ret %3
    }
    """
    ctx = parse_venom(code)

    asm = VenomCompiler(ctx).generate_evm_assembly()
    assert asm == ["SWAP2", "PUSH1", 117, "POP", "MSTORE", "MSTORE", "JUMP"]


def test_invoke_middle_output_unused():
    code = """
    function main {
    main:
        %a, %b, %c = invoke @callee
        return %a, %c
    }

    function callee {
    callee:
        %retpc = param
        %x = 1
        %y = 2
        %z = 3
        ret %x, %y, %z, %retpc
    }
    """
    ctx = parse_venom(code)
    asm = VenomCompiler(ctx).generate_evm_assembly()

    assert "POP" in asm, f"expected POP to remove dead output, got {asm}"
    pop_idx = asm.index("POP")
    assert pop_idx > 0 and asm[pop_idx - 1] == "SWAP1", asm
    assert "RETURN" in asm, asm
    return_idx = asm.index("RETURN")
    assert return_idx > pop_idx and asm[return_idx - 1] == "SWAP1", asm

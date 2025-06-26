from vyper.evm.assembler.core import PUSHLABEL, Label
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


def test_global_vars():
    code = """
    global_var: 10

    function foo {
        main:
            %1 = 1
            %2 = 2
            %3 = add %1, @global_var
            ret %3
    }
    """
    ctx = parse_venom(code)
    asm = VenomCompiler(ctx).generate_evm_assembly()
    assert asm == [
        Label("global_var"),
        "PUSH1",
        1,
        "PUSH1",
        2,
        "POP",
        PUSHLABEL(Label("global_var")),
        "ADD",
        "JUMP",
    ]

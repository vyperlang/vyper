from vyper.venom.basicblock import IRVariable
from vyper.venom.context import IRContext
from vyper.venom.parser import parse_venom
from vyper.venom.stack_model import StackModel
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
    """
    test pop of middle output of invoke
    """
    code = """
    function main {
    main:
        %a, %b, %c = invoke @callee
        mstore %a, %c
        jnz %a, @end1, @end2

    end1:
        stop

    end2:
        stop
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

    assert "POP" in asm, asm
    assert asm.count("POP") == 1, asm
    pop_idx = asm.index("POP")
    assert pop_idx > 0 and asm[pop_idx - 1] == "SWAP1", asm


def test_popmany_bulk_removal_of_suffix():
    compiler = VenomCompiler(IRContext())
    stack = StackModel()
    keep1 = IRVariable("%keep1")
    drop1 = IRVariable("%drop1")
    keep = IRVariable("%keep")

    stack.push(keep1)
    stack.push(drop1)
    stack.push(keep)

    asm: list[str] = []
    compiler.popmany(asm, [drop1], stack)

    assert asm == ["SWAP1", "POP"]
    assert stack._stack == [keep1, keep]


def test_popmany_bulk_removal_of_suffix2():
    compiler = VenomCompiler(IRContext())
    stack = StackModel()
    drop2 = IRVariable("%drop2")
    drop1 = IRVariable("%drop1")
    keep = IRVariable("%keep")

    stack.push(drop2)
    stack.push(drop1)
    stack.push(keep)

    asm: list[str] = []
    compiler.popmany(asm, [drop1, drop2], stack)

    assert asm == ["SWAP2", "POP", "POP"]
    assert stack._stack == [keep]


def test_popmany_falls_back_for_non_contiguous():
    compiler = VenomCompiler(IRContext())
    stack = StackModel()
    drop3 = IRVariable("%drop3")
    keep_mid = IRVariable("%keep_mid")
    drop2 = IRVariable("%drop2")
    keep_top = IRVariable("%keep_top")

    stack.push(drop3)
    stack.push(keep_mid)
    stack.push(drop2)
    stack.push(keep_top)

    asm: list[str] = []
    compiler.popmany(asm, [drop3, drop2], stack)

    assert asm == ["SWAP1", "POP", "SWAP2", "POP"]
    assert len(stack._stack) == 2
    assert keep_mid in stack._stack
    assert keep_top in stack._stack


def test_popmany_uses_swap16_for_contiguous_suffix():
    compiler = VenomCompiler(IRContext())
    stack = StackModel()
    keep_bottom = IRVariable("%keep_bottom")
    stack.push(keep_bottom)
    drops = [IRVariable(f"%drop{i}") for i in range(16, 0, -1)]
    for drop in drops:
        stack.push(drop)
    keep_top = IRVariable("%keep_top")
    stack.push(keep_top)

    asm: list[str] = []
    compiler.popmany(asm, drops, stack)

    assert asm == ["SWAP16"] + ["POP"] * len(drops)
    assert stack._stack == [keep_bottom, keep_top]


def test_popmany_falls_back_when_swap_depth_too_large():
    compiler = VenomCompiler(IRContext())
    stack = StackModel()
    drops = [IRVariable(f"%drop{i}") for i in range(1, 18)]
    keep = IRVariable("%keep")

    for drop in drops:
        stack.push(drop)
    stack.push(keep)

    asm: list[str] = []
    compiler.popmany(asm, drops, stack)

    assert asm == ["SWAP1", "POP"] * len(drops)
    assert stack._stack == [keep]

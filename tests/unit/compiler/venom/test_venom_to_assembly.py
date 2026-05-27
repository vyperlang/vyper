from vyper.compiler import compile_code
from vyper.compiler.settings import Settings
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


def test_popmany_ignores_values_not_on_current_stack():
    compiler = VenomCompiler(IRContext())

    keep = IRVariable("%keep")
    dead = IRVariable("%dead")
    missing = IRVariable("%missing")

    stack = StackModel()
    stack.push(keep)
    stack.push(dead)

    assembly: list = []

    compiler.popmany(assembly, [missing, dead], stack)

    assert assembly == ["POP"]
    assert stack._stack == [keep]

    compiler.popmany(assembly, [missing], stack)

    assert assembly == ["POP"]
    assert stack._stack == [keep]


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


def test_issue_4933_stack_cleanup_compile_regression():
    source = """
# Source from gh-4933. The original version pragma is omitted so this
# regression follows the compiler version under test.

@internal
def GZYui8xZQHbNtw_hexAq() -> uint32:

    return self.XWggREdv8vcwHKle6hx62u()

@internal
def _zsjz7cwknRFFIZIJ4KgTl6sIbscTAH() -> uint32:

    return convert(2769780188, uint32)

@internal
def XWggREdv8vcwHKle6hx62u() -> uint32:

    return convert(141355714, uint32)

@external
def check_entrypoint(assert_in0: uint32, assert_in1: uint32, assert_in2: bool, assert_in3: bool, assert_in4: bool):  # noqa: E501
    local_v_oUGBV: DynArray[uint32, 1024] = []
    local_v_oUGBV.append(convert(165, uint32))
    local_dtRbdy47P: DynArray[uint32, 1024] = []
    local_dtRbdy47P.append(convert(14, uint32))
    local_emZM20f44jaA6PudAp4Cv5: DynArray[uint32, 1024] = []
    local_emZM20f44jaA6PudAp4Cv5.append(convert(153, uint32))
    local_U0Cu7T88: DynArray[bool, 1024] = []
    local_U0Cu7T88.append(True)
    assert_in5: DynArray[uint32, 1024] = []
    assert_in5.append(self.GZYui8xZQHbNtw_hexAq())
    assert_in5.append(convert(3227580517, uint32))
    assert_in5.append(convert(1706635049, uint32))
    assert_in5.append(convert(3957816457, uint32))
    assert_in6: DynArray[uint32, 1024] = []
    assert_in6.append(convert(629905054, uint32))
    assert_in6.append(convert(3632234273, uint32))
    assert_in6.append(convert(545415690, uint32))
    assert_in6.append(convert(216673293, uint32))
    assert_in6.append(convert(1426785817, uint32))
    assert_in6.append(convert(3155107511, uint32))
    assert_in6.append(convert(4001560063, uint32))
    assert_in6.append(convert(1280311583, uint32))
    assert_in6.append(convert(1094737452, uint32))
    assert_in6.append(convert(2864175339, uint32))
    assert_in6.append(convert(191647291, uint32))
    assert_in6.append(self._zsjz7cwknRFFIZIJ4KgTl6sIbscTAH())

    assert_in6.append(convert(676588388, uint32))
    assert_in6.append(convert(589453109, uint32))
    assert_in6.append(convert(362474918, uint32))
    assert_in6.append(convert(3990545660, uint32))
    assert_out1: bool = ((- convert(assert_in1, int32)) < convert(unsafe_sub(assert_in6[convert(14, uint32)], assert_in1), int32))  # noqa: E501
    assert_out2: bool = (((unsafe_mul(convert(unsafe_sub(unsafe_mul(unsafe_div(convert(0, uint32), convert(1, uint32)), convert(1, uint32)), (assert_in1 & (unsafe_add(convert(165, uint32), unsafe_sub(assert_in1, local_v_oUGBV[0])) & unsafe_add(unsafe_sub(assert_in1, convert(165, uint32)), convert(165, uint32))))), int32), (- (- convert(convert(1, uint32), int32)))) < unsafe_add(unsafe_sub(convert(assert_in6[local_dtRbdy47P[0]], int32), unsafe_div((convert(convert(0, uint32), int32) | unsafe_sub(convert(assert_in1, int32), unsafe_add((convert(convert(0, uint32), int32) & unsafe_sub(unsafe_div(unsafe_mul(unsafe_div((- convert(unsafe_sub(convert(0, uint32), (convert(0, uint32) & convert(0, uint32))), int32)), convert(convert(1, uint32), int32)), (- unsafe_add(unsafe_sub((- convert(convert(1, uint32), int32)), unsafe_sub((- (- convert((convert(106, uint32) & convert(106, uint32)), int32))), unsafe_add((- convert(convert(183, uint32), int32)), convert(convert(183, uint32), int32)))), convert(convert(106, uint32), int32)))), convert(convert(1, uint32), int32)), convert((convert(153, uint32) & convert(0, uint32)), int32))), convert(unsafe_mul(convert(0, uint32), convert(1, uint32)), int32)))), convert(unsafe_div(convert(1, uint32), convert(1, uint32)), int32))), convert((convert(73, uint32) & convert(0, uint32)), int32))) or (unsafe_mul(convert(unsafe_sub(unsafe_mul(unsafe_div(convert(0, uint32), convert(1, uint32)), convert(1, uint32)), (assert_in1 & (unsafe_add(convert(165, uint32), unsafe_sub(assert_in1, convert(165, uint32))) & unsafe_add(unsafe_sub(assert_in1, convert(165, uint32)), convert(165, uint32))))), int32), (- (- convert(convert(1, uint32), int32)))) < unsafe_add(unsafe_sub(convert(assert_in6[convert(14, uint32)], int32), unsafe_div((convert(convert(0, uint32), int32) | unsafe_sub(convert(assert_in1, int32), unsafe_add((convert(convert(0, uint32), int32) & unsafe_sub(unsafe_div(unsafe_mul(unsafe_div((- convert(unsafe_sub(convert(0, uint32), (convert(0, uint32) & convert(0, uint32))), int32)), convert(convert(1, uint32), int32)), (- unsafe_add((unsafe_sub((- convert(convert(1, uint32), int32)), unsafe_sub((- (- convert((convert(106, uint32) & convert(106, uint32)), int32))), unsafe_add((- convert(convert(183, uint32), int32)), convert(convert(183, uint32), int32)))) | convert(convert(0, uint32), int32)), convert(convert(106, uint32), int32)))), convert(convert(1, uint32), int32)), convert((local_emZM20f44jaA6PudAp4Cv5[0] & convert(0, uint32)), int32))), convert(unsafe_mul(convert(0, uint32), convert(1, uint32)), int32)))), convert(unsafe_div(convert(1, uint32), convert(1, uint32)), int32))), convert((convert(73, uint32) & convert(0, uint32)), int32)))) and (not (not (True and (((not (not local_U0Cu7T88[0])) and (not (not (True and True)))) or (((not False) and (not (not ((True or False) and ((True and True) or (False or False)))))) or False))))))  # noqa: E501
    assert (assert_out1 == assert_out2)
"""
    settings = Settings(experimental_codegen=True)

    out = compile_code(source, settings=settings, output_formats=["bytecode_runtime"])

    assert out["bytecode_runtime"].startswith("0x")

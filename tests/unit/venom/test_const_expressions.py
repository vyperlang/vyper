import pytest

from vyper.evm.assembler.core import assembly_to_evm
from vyper.evm.assembler.symbols import CONST, Label
from vyper.venom.basicblock import IRLabel, IRLiteral
from vyper.venom.const_eval import ConstEvalException, evaluate_const_expr, try_evaluate_const_expr
from vyper.venom.parser import parse_venom
from vyper.venom.venom_to_assembly import VenomCompiler


def test_basic_const_eval():
    constants = {"A": 10, "B": 20}
    global_labels = {"label1": 0x100, "label2": 0x200}

    # Test literals
    assert evaluate_const_expr(42, constants, global_labels) == 42

    # Test constant references
    assert evaluate_const_expr("$A", constants, global_labels) == 10
    assert evaluate_const_expr("$B", constants, global_labels) == 20

    # Test label references
    assert evaluate_const_expr("@label1", constants, global_labels) == 0x100
    assert evaluate_const_expr("@label2", constants, global_labels) == 0x200

    # Test operations
    assert evaluate_const_expr(("add", 10, 20), constants, global_labels) == 30
    assert evaluate_const_expr(("sub", 50, 20), constants, global_labels) == 30
    assert evaluate_const_expr(("mul", 5, 6), constants, global_labels) == 30
    assert evaluate_const_expr(("div", 60, 2), constants, global_labels) == 30
    assert evaluate_const_expr(("mod", 32, 5), constants, global_labels) == 2
    assert evaluate_const_expr(("max", 10, 20), constants, global_labels) == 20
    assert evaluate_const_expr(("min", 10, 20), constants, global_labels) == 10

    # Test operations with references
    assert evaluate_const_expr(("add", "$A", "$B"), constants, global_labels) == 30
    assert evaluate_const_expr(("add", "@label1", 0x100), constants, global_labels) == 0x200

    # Test nested operations
    assert evaluate_const_expr(("add", ("mul", 2, 3), 4), constants, global_labels) == 10
    assert evaluate_const_expr(("mul", ("add", "$A", 5), 2), constants, global_labels) == 30


def test_const_eval_errors():
    constants = {"A": 10}
    global_labels = {"label1": 0x100}

    # Test undefined constant
    with pytest.raises(ConstEvalException, match="Undefined constant: B"):
        evaluate_const_expr("$B", constants, global_labels)

    # Test undefined label
    with pytest.raises(ConstEvalException, match="Undefined global label: label2"):
        evaluate_const_expr("@label2", constants, global_labels)

    # Test division by zero
    with pytest.raises(ConstEvalException, match="Division by zero"):
        evaluate_const_expr(("div", 10, 0), constants, global_labels)

    # Test modulo by zero
    with pytest.raises(ConstEvalException, match="Modulo by zero"):
        evaluate_const_expr(("mod", 10, 0), constants, global_labels)

    # Test unknown operation
    with pytest.raises(ConstEvalException, match="Unknown operation: unknown_op"):
        evaluate_const_expr(("unknown_op", 10, 20), constants, global_labels)


def test_venom_const_definitions():
    code = """
    const SLOT_SIZE = 32
    const BASE_ADDR = 0x1000
    const SLOT_2 = mul($SLOT_SIZE, 2)
    const DATA_START = add($BASE_ADDR, $SLOT_2)

    data_label: $DATA_START

    function main {
        entry:
            ret
    }
    """

    ctx = parse_venom(code)

    # Check constants
    assert ctx.constants["SLOT_SIZE"] == 32
    assert ctx.constants["BASE_ADDR"] == 0x1000
    assert ctx.constants["SLOT_2"] == 64
    assert ctx.constants["DATA_START"] == 0x1040

    # Check global label
    assert ctx.global_labels["data_label"] == 0x1040


def test_venom_label_addresses():
    """Test that label addresses can be used in const expressions."""
    code = """
    const BASE = 0x100
    const OFFSET = 0x20

    data_label: 0x1000
    computed_label: add(@data_label, $OFFSET)

    function main {
        entry:
            %1 = @data_label
            %2 = @computed_label
            return %1, %2
    }
    """

    ctx = parse_venom(code)

    # Check global labels
    assert ctx.global_labels["data_label"] == 0x1000
    assert ctx.global_labels["computed_label"] == 0x1020

    # Check that labels are used in instructions
    fn = ctx.entry_function
    bb = fn.get_basic_block("entry")
    instructions = bb.instructions

    # Labels in instructions should be IRLabel objects
    assert instructions[0].opcode == "store"
    assert isinstance(instructions[0].operands[0], IRLabel)
    assert instructions[0].operands[0].value == "data_label"

    assert instructions[1].opcode == "store"
    assert isinstance(instructions[1].operands[0], IRLabel)
    assert instructions[1].operands[0].value == "computed_label"


def test_venom_instruction_operands():
    code = """
    const SLOT_SIZE = 32
    const NUM_SLOTS = 4

    data_label: 0x2000

    function main {
        entry:
            %1 = $SLOT_SIZE
            %2 = mul($SLOT_SIZE, $NUM_SLOTS)
            %3 = add(@data_label, 16)
            %4 = max($SLOT_SIZE, 64)
            return %3, %4
    }
    """

    ctx = parse_venom(code)
    fn = ctx.entry_function
    bb = fn.get_basic_block("entry")

    instructions = bb.instructions

    # Check store instructions have evaluated operands
    assert instructions[0].opcode == "store"
    assert instructions[0].operands[0].value == 32

    assert instructions[1].opcode == "store"
    assert instructions[1].operands[0].value == 128

    assert instructions[2].opcode == "store"
    assert instructions[2].operands[0].value == 0x2010

    assert instructions[3].opcode == "store"
    assert instructions[3].operands[0].value == 64


def test_venom_complex_example():
    code = """
    const WORD_SIZE = 32
    const HEADER_SIZE = 64
    const ARRAY_SLOT = 5
    const ARRAY_OFFSET = mul($ARRAY_SLOT, $WORD_SIZE)
    const DATA_START = add($HEADER_SIZE, $ARRAY_OFFSET)

    array_data: $DATA_START
    array_end: add(@array_data, mul($WORD_SIZE, 10))

    function process_array {
        loop_start:
            %ptr = mload 0
            %val = mload %ptr
            %next_ptr = add %ptr, $WORD_SIZE
            mstore 0, %next_ptr
            %done = ge %next_ptr, @array_end
            %should_continue = iszero %done
            jnz %should_continue, @loop_start, @finish

        finish:
            return %ptr, %val
    }
    """

    ctx = parse_venom(code)

    # Check computed constants
    assert ctx.constants["ARRAY_OFFSET"] == 160
    assert ctx.constants["DATA_START"] == 224

    # Check global labels
    assert ctx.global_labels["array_data"] == 224
    assert ctx.global_labels["array_end"] == 224 + 320  # 544

    # Check instruction operands
    fn = ctx.get_function(ctx.functions[list(ctx.functions.keys())[0]].name)
    bb = fn.get_basic_block("loop_start")

    # Find the add instruction
    add_inst = None
    for inst in bb.instructions:
        if inst.opcode == "add":
            add_inst = inst
            break

    assert add_inst is not None
    assert add_inst.operands[0].value == 32


def test_try_evaluate_undefined_const():
    """Test that try_evaluate returns labels for undefined constants."""
    constants = {"A": 10}
    global_labels = {"label1": 0x100}
    unresolved_consts = {}
    const_refs = set()

    # Test defined constant - returns value
    result = try_evaluate_const_expr("$A", constants, global_labels, unresolved_consts, const_refs)
    assert result == 10
    assert len(unresolved_consts) == 0
    assert len(const_refs) == 0

    # Test undefined constant - returns label
    result = try_evaluate_const_expr("$B", constants, global_labels, unresolved_consts, const_refs)
    assert isinstance(result, str)
    assert result == "B"  # Now uses the constant name directly
    assert "B" in const_refs
    assert result in unresolved_consts
    assert unresolved_consts[result] == ("ref", "B")


def test_try_evaluate_undefined_in_operation():
    """Test operations with undefined constants."""
    constants = {"A": 10}
    global_labels = {}
    unresolved_consts = {}
    const_refs = set()

    # Operation with one undefined constant
    result = try_evaluate_const_expr(
        ("add", "$A", "$B"), constants, global_labels, unresolved_consts, const_refs
    )
    assert isinstance(result, str)
    assert result.startswith("__const_")  # Complex expressions still get generated names
    assert "B" in const_refs

    # Check that the unresolved expression is stored correctly
    assert result in unresolved_consts
    op_name, arg1, arg2 = unresolved_consts[result]
    assert op_name == "add"
    assert arg1 == 10  # A was resolved
    assert isinstance(arg2, str) and arg2 == "B"  # B is unresolved

    # Operation with both undefined
    unresolved_consts.clear()
    const_refs.clear()
    result = try_evaluate_const_expr(
        ("mul", "$B", "$C"), constants, global_labels, unresolved_consts, const_refs
    )
    assert isinstance(result, str)
    assert result.startswith("__const_")
    assert "B" in const_refs
    assert "C" in const_refs


def test_venom_with_undefined_constants():
    """Test parsing Venom code with undefined constants in instructions."""
    code = """
    const A = 100

    function main {
        entry:
            %1 = $A
            %2 = add $A, $UNDEFINED
            %3 = mul $UNDEFINED2, 10
            ret
    }
    """

    ctx = parse_venom(code)

    # Check that defined constant is resolved
    assert ctx.constants["A"] == 100

    # Check that undefined references are tracked
    assert len(ctx.const_refs) >= 2 or len(ctx.unresolved_consts) >= 2

    # Check instructions
    fn = ctx.entry_function
    bb = fn.get_basic_block("entry")
    instructions = bb.instructions

    # First instruction should have resolved value
    assert instructions[0].opcode == "store"
    assert isinstance(instructions[0].operands[0], IRLiteral)
    assert instructions[0].operands[0].value == 100

    # Second instruction should be add with label for unresolved expression
    assert instructions[1].opcode == "add"
    # At least one operand should be a label
    has_label = any(isinstance(op, IRLabel) for op in instructions[1].operands)
    assert has_label

    # Third instruction should be mul with label for unresolved expression
    assert instructions[2].opcode == "mul"
    has_label = any(isinstance(op, IRLabel) for op in instructions[2].operands)
    assert has_label


def test_venom_undefined_in_instruction_operands():
    """Test undefined constants used directly in instruction operands."""
    code = """
    const SIZE = 32

    function test {
        entry:
            %1 = add $SIZE, $UNDEFINED_OFFSET
            %2 = mul $UNDEFINED_FACTOR, 10
            mstore $UNDEFINED_ADDR, %1
            ret
    }
    """

    ctx = parse_venom(code)

    # Check that undefined constants are tracked
    assert len(ctx.const_refs) > 0
    assert "UNDEFINED_OFFSET" in ctx.const_refs or len(ctx.unresolved_consts) > 0

    fn = ctx.entry_function
    bb = fn.get_basic_block("entry")

    # Check add instruction - should use labels for unresolved expressions
    add_inst = next(inst for inst in bb.instructions if inst.opcode == "add")
    # At least one operand should be a label (for the unresolved expression)
    has_label = any(isinstance(op, IRLabel) for op in add_inst.operands)
    assert has_label

    # Check mul instruction
    mul_inst = next(inst for inst in bb.instructions if inst.opcode == "mul")
    has_label = any(isinstance(op, IRLabel) for op in mul_inst.operands)
    assert has_label


def test_complex_undefined_chain():
    """Test complex chains of undefined constants."""
    code = """
    const BASE = 100
    const STEP = 10

    function compute {
        entry:
            %1 = add $BASE, $UNDEFINED_A
            %2 = mul %1, $STEP
            %3 = add %2, $UNDEFINED_B
            %4 = max %3, $BASE
            ret %4
    }
    """

    ctx = parse_venom(code)

    # Should track multiple undefined constants
    assert len(ctx.const_refs) >= 2 or len(ctx.unresolved_consts) >= 2

    # The computation chain should work even with undefined constants
    fn = ctx.entry_function
    bb = fn.get_basic_block("entry")
    assert len(bb.instructions) >= 5  # 4 computations + ret


def test_undefined_const_end_to_end():
    """Test end-to-end compilation with undefined constants that get resolved in assembly."""
    code = """
    const DEFINED_A = 100

    function main {
        entry:
            %1 = $DEFINED_A
            %2 = $UNDEFINED_X
            %3 = 0
            %4 = 32
            mstore %1, %3
            mstore %2, %4
            stop
    }
    """

    ctx = parse_venom(code)

    assert len(ctx.const_refs) >= 1
    assert "UNDEFINED_X" in ctx.const_refs

    # Generate assembly
    compiler = VenomCompiler(ctx)
    asm = compiler.generate_evm_assembly(no_optimize=True)

    assert len(ctx.unresolved_consts) >= 1

    # Now add the missing constant definitions to the assembly
    # This simulates the "linking" step where external constants are provided
    # Since we use the actual constant names, we can just add them directly
    asm.insert(0, CONST("UNDEFINED_X", 50))

    bytecode, _ = assembly_to_evm(asm)

    assert len(bytecode) > 0


def test_undefined_const_with_operations():
    code = """
    const BASE = 1000

    function compute {
        entry:
            %1 = add $BASE, $EXTERNAL_OFFSET
            %2 = sub %1, $EXTERNAL_FEE
            %3 = add %2, $EXTERNAL_BONUS
            ret %3
    }
    """

    ctx = parse_venom(code)

    # Generate assembly
    compiler = VenomCompiler(ctx)
    asm = compiler.generate_evm_assembly(no_optimize=True)

    # Add the external constant definitions directly by name
    asm.insert(0, CONST("EXTERNAL_OFFSET", 500))
    asm.insert(0, CONST("EXTERNAL_FEE", 100))
    asm.insert(0, CONST("EXTERNAL_BONUS", 50))

    bytecode, _ = assembly_to_evm(asm)
    assert len(bytecode) > 0


def test_undefined_const_linking_example():
    """Example showing how external constants can be linked in a clean way."""
    # Venom code using external constants and labels
    code = """
    const SLOT_SIZE = 32

    function storage_access {
        entry:
            %slot = add $STORAGE_BASE, $SLOT_OFFSET
            %addr = mul %slot, $SLOT_SIZE
            %val = sload @deploy_addr
            return %val
    }
    """

    ctx = parse_venom(code)
    compiler = VenomCompiler(ctx)
    asm = compiler.generate_evm_assembly(no_optimize=True)

    asm.insert(0, CONST("STORAGE_BASE", 0x1000))
    asm.insert(0, CONST("SLOT_OFFSET", 5))
    asm.insert(0, Label("deploy_addr"))

    # Compile to bytecode
    bytecode, _ = assembly_to_evm(asm)
    assert len(bytecode) > 0

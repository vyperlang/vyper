from vyper.venom.parser import parse_venom


def test_empty_db_instruction():
    """Test that db x"" is accepted by the parser."""
    venom_code = """
    function test_data {
        test_data:
            db x""
    }
    """
    
    ctx = parse_venom(venom_code)
    
    from vyper.venom.basicblock import IRLabel
    assert IRLabel("test_data") in ctx.functions
    
    fn = ctx.functions[IRLabel("test_data")]
    bb = fn.get_basic_block("test_data")
    assert len(bb.instructions) == 1
    assert bb.instructions[0].opcode == "db"


def test_db_with_data():
    venom_code = """
    function test_data {
        test_data:
            db x"deadbeef"
    }
    """
    
    ctx = parse_venom(venom_code)
    
    from vyper.venom.basicblock import IRLabel
    assert IRLabel("test_data") in ctx.functions
    fn = ctx.functions[IRLabel("test_data")]
    bb = fn.get_basic_block("test_data")
    assert len(bb.instructions) == 1
    assert bb.instructions[0].opcode == "db"
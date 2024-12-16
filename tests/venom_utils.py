from vyper.venom.basicblock  import IRBasicBlock, IRInstruction
from vyper.venom.function import IRFunction
from vyper.venom.context import IRContext

def instructions_eq(i1: IRInstruction, i2: IRInstruction) -> bool:
    return i1.output == i2.output and i1.opcode == i2.opcode and i1.operands == i2.operands
 
 
def assert_bb_eq(bb1: IRBasicBlock, bb2: IRBasicBlock):
    assert bb1.label.value == bb2.label.value
    assert len(bb1.instructions) == len(bb2.instructions)
    for i1, i2 in zip(bb1.instructions, bb2.instructions):
        assert instructions_eq(i1, i2), f"[{i1}] != [{i2}]"
 
 
def assert_fn_eq(fn1: IRFunction, fn2: IRFunction):
    assert fn1.name.value == fn2.name.value
    assert fn1.last_variable == fn2.last_variable
    assert len(fn1._basic_block_dict) == len(fn2._basic_block_dict)
 
    for name1, bb1 in fn1._basic_block_dict.items():
        assert name1 in fn2._basic_block_dict
        assert_bb_eq(bb1, fn2._basic_block_dict[name1])
 
    # check function entry is the same
    assert fn1.entry.label == fn2.entry.label
 
 
def assert_ctx_eq(ctx1: IRContext, ctx2: IRContext):
    assert ctx1.last_label == ctx2.last_label
    assert len(ctx1.functions) == len(ctx2.functions)
    for label1, fn1 in ctx1.functions.items():
        assert label1 in ctx2.functions
        assert_fn_eq(fn1, ctx2.functions[label1])
 
    # check entry function is the same
    assert next(iter(ctx1.functions.keys())) == next(iter(ctx2.functions.keys()))
 
    assert len(ctx1.data_segment) == len(ctx2.data_segment)
    for d1, d2 in zip(ctx1.data_segment, ctx2.data_segment):
        assert instructions_eq(d1, d2), f"data: [{d1}] != [{d2}]"
 


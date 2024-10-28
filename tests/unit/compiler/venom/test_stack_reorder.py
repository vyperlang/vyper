from vyper.venom import generate_assembly_experimental
from vyper.venom.analysis import IRAnalysesCache
from vyper.venom.context import IRContext
from vyper.venom.passes import StoreExpansionPass


def test_stack_reorder():
    """
    Test to was created from the example in the
    issue https://github.com/vyperlang/vyper/issues/4215
    this example should fail with original stack reorder
    algorithm but succeed with new one
    """
    ctx = IRContext()
    fn = ctx.create_function("_global")

    bb = fn.get_basic_block()
    var0 = bb.append_instruction("store", 1)
    var1 = bb.append_instruction("store", 2)
    var2 = bb.append_instruction("store", 3)
    var3 = bb.append_instruction("store", 4)
    var4 = bb.append_instruction("store", 5)

    bb.append_instruction("staticcall", var0, var1, var2, var3, var4, var3)

    ret_val = bb.append_instruction("add", var4, var4)

    bb.append_instruction("ret", ret_val)

    ac = IRAnalysesCache(fn)
    StoreExpansionPass(ac, fn).run_pass()

    generate_assembly_experimental(ctx)

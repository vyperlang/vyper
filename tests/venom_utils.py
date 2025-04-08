from vyper.venom.analysis import IRAnalysesCache
from vyper.venom.basicblock import IRBasicBlock, IRInstruction
from vyper.venom.context import IRContext
from vyper.venom.function import IRFunction
from vyper.venom.parser import parse_venom
from vyper.venom.passes.base_pass import IRPass


def parse_from_basic_block(source: str, funcname="_global"):
    """
    Parse an IRContext from a basic block
    """
    source = f"function {funcname} {{\n{source}\n}}"
    return parse_venom(source)


def instructions_eq(i1: IRInstruction, i2: IRInstruction) -> bool:
    return i1.output == i2.output and i1.opcode == i2.opcode and i1.operands == i2.operands


def assert_bb_eq(bb1: IRBasicBlock, bb2: IRBasicBlock):
    assert bb1.label.value == bb2.label.value
    for i1, i2 in zip(bb1.instructions, bb2.instructions):
        assert instructions_eq(i1, i2), (bb1, f"[{i1}] != [{i2}]")

    # assert after individual instruction checks, makes it easier to debug
    # if there is a difference.
    assert len(bb1.instructions) == len(bb2.instructions)


def assert_fn_eq(fn1: IRFunction, fn2: IRFunction):
    assert fn1.name.value == fn2.name.value
    assert len(fn1._basic_block_dict) == len(fn2._basic_block_dict)

    for name1, bb1 in fn1._basic_block_dict.items():
        assert name1 in fn2._basic_block_dict
        assert_bb_eq(bb1, fn2._basic_block_dict[name1])

    # check function entry is the same
    assert fn1.entry.label == fn2.entry.label


def assert_ctx_eq(ctx1: IRContext, ctx2: IRContext):
    for label1, fn1 in ctx1.functions.items():
        assert label1 in ctx2.functions
        assert_fn_eq(fn1, ctx2.functions[label1])
    assert len(ctx1.functions) == len(ctx2.functions)

    # check entry function is the same
    assert next(iter(ctx1.functions.keys())) == next(iter(ctx2.functions.keys()))
    assert ctx1.data_segment == ctx2.data_segment, ctx2.data_segment


class PrePostChecker:
    passes: list[type]
    post_passes: list[type]
    pass_objects: list[IRPass]
    default_hevm: bool

    def __init__(self, passes: list[type], post: list[type] = None, default_hevm: bool = True):
        self.passes = passes
        if post is None:
            self.post_passes = []
        else:
            self.post_passes = post
        self.default_hevm = default_hevm
        self.pass_objects = list()

    def __call__(self, pre: str, post: str, hevm: bool | None = None) -> list[IRPass]:
        from tests.hevm import hevm_check_venom

        self.pass_objects.clear()

        if hevm is None:
            hevm = self.default_hevm

        pre_ctx = parse_from_basic_block(pre)
        for fn in pre_ctx.functions.values():
            ac = IRAnalysesCache(fn)
            for p in self.passes:
                obj = p(ac, fn)
                self.pass_objects.append(obj)
                obj.run_pass()

        post_ctx = parse_from_basic_block(post)
        for fn in post_ctx.functions.values():
            ac = IRAnalysesCache(fn)
            for p in self.post_passes:
                obj = p(ac, fn)
                self.pass_objects.append(obj)
                obj.run_pass()

        assert_ctx_eq(pre_ctx, post_ctx)

        if hevm:
            hevm_check_venom(pre, post)

        return self.pass_objects

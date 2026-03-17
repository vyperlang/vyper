from vyper.compiler import compile_code
from vyper.compiler.settings import OptimizationLevel, Settings, VenomOptimizationFlags
from vyper.venom.basicblock import IRVariable


def test_annassign_internal_call_result_reuses_return_buffer():
    code = """
@internal
def _id(a: uint256[2]) -> uint256[2]:
    return a

@internal
def _sum(a: uint256[2]) -> uint256:
    return a[0] + a[1]

@internal
def _driver(a: uint256[2]) -> uint256:
    tmp: uint256[2] = self._id(a)
    return self._sum(tmp)

@external
def foo() -> uint256:
    x: uint256[2] = [1, 2]
    return self._driver(x)
    """

    settings = Settings(experimental_codegen=True, optimize=OptimizationLevel.O3)
    settings.venom_flags = VenomOptimizationFlags(level=OptimizationLevel.O3, disable_inlining=True)

    ctx = compile_code(code, settings=settings, output_formats=["ir_runtime"])["ir_runtime"]

    driver_fn = next(fn for fn in ctx.functions.values() if "_driver" in str(fn.name))
    opcodes = [inst.opcode for bb in driver_fn.get_basic_blocks() for inst in bb.instructions]

    # Ensure the test is meaningful: _driver should still perform both calls.
    assert opcodes.count("invoke") >= 2
    # tmp should bind to _id's return buffer, not emit an intermediate copy.
    assert "mcopy" not in opcodes


def test_readonly_internal_memory_arg_is_forwarded_in_backend():
    code = """
@internal
def _sum(a: uint256[2]) -> uint256:
    return a[0] + a[1]

@internal
def _driver() -> uint256:
    x: uint256[2] = [1, 2]
    return self._sum(x)

@external
def foo() -> uint256:
    return self._driver()
    """

    settings = Settings(experimental_codegen=True, optimize=OptimizationLevel.O3)
    settings.venom_flags = VenomOptimizationFlags(level=OptimizationLevel.O3, disable_inlining=True)

    ctx = compile_code(code, settings=settings, output_formats=["ir_runtime"])["ir_runtime"]

    driver_fn = next(fn for fn in ctx.functions.values() if "_driver" in str(fn.name))
    driver_insts = [inst for bb in driver_fn.get_basic_blocks() for inst in bb.instructions]
    opcodes = [inst.opcode for inst in driver_insts]
    invokes = [inst for inst in driver_insts if inst.opcode == "invoke"]
    mcopies = [inst for inst in driver_insts if inst.opcode == "mcopy"]

    # Ensure this path still goes through an internal call.
    assert opcodes.count("invoke") >= 1
    # One mcopy can remain for source value materialization, but invoke should
    # consume that pointer directly (no extra staging mcopy for the call arg).
    assert len(invokes) == 1
    assert len(mcopies) <= 1
    if len(mcopies) == 0:
        return

    invoke_arg = invokes[0].operands[1]
    mcopy_dst = mcopies[0].operands[2]

    defs = {inst.output: inst for inst in driver_insts if inst.num_outputs == 1}

    def _assign_root(op):
        while isinstance(op, IRVariable):
            inst = defs.get(op)
            if inst is None or inst.opcode != "assign":
                break
            src = inst.operands[0]
            if not isinstance(src, IRVariable):
                return src
            op = src
        return op

    assert _assign_root(invoke_arg) == _assign_root(mcopy_dst)


def test_mutable_internal_memory_arg_is_not_forwarded():
    code = """
@internal
def _touch(a: uint256[2]) -> uint256:
    a[0] = 99
    return a[0]

@internal
def _driver() -> uint256:
    x: uint256[2] = [1, 2]
    return self._touch(x)

@external
def foo() -> uint256:
    return self._driver()
    """

    settings = Settings(experimental_codegen=True, optimize=OptimizationLevel.O3)
    settings.venom_flags = VenomOptimizationFlags(level=OptimizationLevel.O3, disable_inlining=True)

    ctx = compile_code(code, settings=settings, output_formats=["ir_runtime"])["ir_runtime"]

    driver_fn = next(fn for fn in ctx.functions.values() if "_driver" in str(fn.name))
    driver_insts = [inst for bb in driver_fn.get_basic_blocks() for inst in bb.instructions]
    invokes = [inst for inst in driver_insts if inst.opcode == "invoke"]
    mcopies = [inst for inst in driver_insts if inst.opcode == "mcopy"]

    assert len(invokes) == 1
    # Mutable callee arg should keep a by-value staging copy.
    assert len(mcopies) >= 1

    defs = {inst.output: inst for inst in driver_insts if inst.num_outputs == 1}

    def _assign_root(op):
        while isinstance(op, IRVariable):
            inst = defs.get(op)
            if inst is None or inst.opcode != "assign":
                break
            src = inst.operands[0]
            if not isinstance(src, IRVariable):
                return src
            op = src
        return op

    invoke_root = _assign_root(invokes[0].operands[1])
    mcopy_dst_roots = {_assign_root(inst.operands[2]) for inst in mcopies}
    assert invoke_root in mcopy_dst_roots


def test_non_return_invoke_source_copy_is_not_forwarded():
    code = """
@internal
def _touch(a: uint256[2]):
    a[0] = 99

@internal
def _driver() -> uint256:
    x: uint256[2] = [1, 2]
    self._touch(x)
    y: uint256[2] = x
    x[0] = 7
    return y[0]

@external
def foo() -> uint256:
    return self._driver()
    """

    settings = Settings(experimental_codegen=True, optimize=OptimizationLevel.O3)
    settings.venom_flags = VenomOptimizationFlags(level=OptimizationLevel.O3, disable_inlining=True)

    ctx = compile_code(code, settings=settings, output_formats=["ir_runtime"])["ir_runtime"]

    driver_fn = next(fn for fn in ctx.functions.values() if "_driver" in str(fn.name))
    opcodes = [inst.opcode for bb in driver_fn.get_basic_blocks() for inst in bb.instructions]

    # Copy from x into y must remain because x is mutated afterwards.
    assert "mcopy" in opcodes


def test_readonly_propagates_transitively_across_internal_calls():
    code = """
@internal
def _sum(a: uint256[2]) -> uint256:
    return a[0] + a[1]

@internal
def _wrap(a: uint256[2]) -> uint256:
    return self._sum(a)

@internal
def _driver() -> uint256:
    x: uint256[2] = [1, 2]
    return self._wrap(x)

@external
def foo() -> uint256:
    return self._driver()
    """

    settings = Settings(experimental_codegen=True, optimize=OptimizationLevel.O3)
    settings.venom_flags = VenomOptimizationFlags(level=OptimizationLevel.O3, disable_inlining=True)

    ctx = compile_code(code, settings=settings, output_formats=["ir_runtime"])["ir_runtime"]

    driver_fn = next(fn for fn in ctx.functions.values() if "_driver" in str(fn.name))
    opcodes = [inst.opcode for bb in driver_fn.get_basic_blocks() for inst in bb.instructions]

    assert opcodes.count("invoke") >= 1
    # `_wrap` should be inferred readonly and allow forwarding at `_driver`.
    assert "mcopy" not in opcodes

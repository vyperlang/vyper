import pytest

import vyper.venom as venom
from vyper.compiler.settings import OptimizationLevel, VenomOptimizationFlags
from vyper.exceptions import CompilerPanic
from vyper.venom.optimization_levels.pass_order import validate_pass_order
from vyper.venom.passes.base_pass import IRPass


@pytest.mark.parametrize(
    "level", [OptimizationLevel.O2, OptimizationLevel.O3, OptimizationLevel.Os]
)
def test_builtin_optimization_pipelines_are_valid(level):
    flags = VenomOptimizationFlags(level=level)
    pipeline = venom._build_fn_pass_pipeline(flags)
    assert len(pipeline) > 0


def test_validate_requires_pass_before():
    class Producer(IRPass):
        pass

    class Consumer(IRPass):
        required_predecessors = (Producer,)

    validate_pass_order([Producer, Consumer], pipeline_name="test")
    with pytest.raises(CompilerPanic, match="Consumer"):
        validate_pass_order([Consumer, Producer], pipeline_name="test")


def test_validate_requires_pass_after():
    class Producer(IRPass):
        required_successors = ("Consumer",)

    class Consumer(IRPass):
        pass

    validate_pass_order([Producer, Consumer], pipeline_name="test")
    with pytest.raises(CompilerPanic, match="Producer"):
        validate_pass_order([Consumer, Producer], pipeline_name="test")


def test_validate_requires_immediate_successor():
    class Producer(IRPass):
        required_immediate_successors = ("Consumer",)

    class Gap(IRPass):
        pass

    class Consumer(IRPass):
        pass

    validate_pass_order([Producer, Consumer], pipeline_name="test")
    with pytest.raises(CompilerPanic, match="Producer"):
        validate_pass_order([Producer, Gap, Consumer], pipeline_name="test")


def test_validate_requires_immediate_predecessor():
    class Producer(IRPass):
        pass

    class Gap(IRPass):
        pass

    class Consumer(IRPass):
        required_immediate_predecessors = ("Producer",)

    validate_pass_order([Producer, Consumer], pipeline_name="test")
    with pytest.raises(CompilerPanic, match="Consumer"):
        validate_pass_order([Producer, Gap, Consumer], pipeline_name="test")


def test_validation_happens_after_disable_flag_filtering(monkeypatch):
    class RequiredPass(IRPass):
        pass

    class DisablablePass(IRPass):
        pass

    RequiredPass.required_successors = (DisablablePass,)

    monkeypatch.setitem(
        venom.OPTIMIZATION_PASSES, OptimizationLevel.O2, [RequiredPass, DisablablePass]
    )
    monkeypatch.setitem(venom.PASS_FLAG_MAP, DisablablePass, "disable_cse")

    with pytest.raises(CompilerPanic, match="RequiredPass"):
        venom._build_fn_pass_pipeline(
            VenomOptimizationFlags(level=OptimizationLevel.O2, disable_cse=True)
        )


def test_legacy_aliases_still_work():
    class Producer(IRPass):
        pass

    class Consumer(IRPass):
        must_run_after = ("Producer",)

    validate_pass_order([Producer, Consumer], pipeline_name="test")


def test_o3_tail_merge_requires_immediate_simplify_cfg():
    with pytest.raises(CompilerPanic, match="TailMergePass"):
        venom._build_fn_pass_pipeline(
            VenomOptimizationFlags(level=OptimizationLevel.O3, disable_simplify_cfg=True)
        )

import pytest

import vyper.venom as venom
from vyper.compiler.settings import OptimizationLevel, VenomOptimizationFlags
from vyper.exceptions import CompilerPanic
from vyper.venom.optimization_levels.pass_order import validate_pass_order
from vyper.venom.passes.base_pass import IRPass
from vyper.venom.passes.cfg_normalization import CFGNormalization
from vyper.venom.passes.concretize_mem_loc import ConcretizeMemLocPass
from vyper.venom.passes.dft import DFTPass
from vyper.venom.passes.fix_mem_locations import FixMemLocationsPass
from vyper.venom.passes.literals_codesize import ReduceLiteralsCodesize
from vyper.venom.passes.make_ssa import MakeSSA
from vyper.venom.passes.mem2var import Mem2Var
from vyper.venom.passes.revert_to_assert import RevertToAssert
from vyper.venom.passes.simplify_cfg import SimplifyCFGPass
from vyper.venom.passes.single_use_expansion import SingleUseExpansion
from vyper.venom.passes.tail_merge import TailMergePass


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


def test_tail_merge_requires_immediate_simplify_cfg():
    validate_pass_order([TailMergePass, SimplifyCFGPass], pipeline_name="test")
    with pytest.raises(CompilerPanic, match="TailMergePass"):
        validate_pass_order([TailMergePass, SingleUseExpansion], pipeline_name="test")


def test_o3_tail_merge_is_immediately_followed_by_simplify_cfg():
    pipeline = venom._build_fn_pass_pipeline(VenomOptimizationFlags(level=OptimizationLevel.O3))
    pass_classes = [pass_cls for pass_cls, _ in pipeline]

    idx = pass_classes.index(TailMergePass)
    assert pass_classes[idx + 1] is SimplifyCFGPass


def test_revert_to_assert_requires_immediate_simplify_cfg():
    validate_pass_order([RevertToAssert, SimplifyCFGPass], pipeline_name="test")
    with pytest.raises(CompilerPanic, match="RevertToAssert"):
        validate_pass_order([RevertToAssert, SingleUseExpansion], pipeline_name="test")


def test_fix_mem_locations_requires_concretize_after():
    class MidPass(IRPass):
        pass

    validate_pass_order([FixMemLocationsPass, MidPass, ConcretizeMemLocPass], pipeline_name="test")
    with pytest.raises(CompilerPanic, match="FixMemLocationsPass"):
        validate_pass_order([FixMemLocationsPass, MidPass], pipeline_name="test")


def test_concretize_requires_fix_mem_locations_before():
    validate_pass_order([FixMemLocationsPass, ConcretizeMemLocPass], pipeline_name="test")
    with pytest.raises(CompilerPanic, match="ConcretizeMemLocPass"):
        validate_pass_order([ConcretizeMemLocPass], pipeline_name="test")


def test_mem2var_requires_make_ssa_before_and_after():
    validate_pass_order([MakeSSA, Mem2Var, MakeSSA], pipeline_name="test")

    with pytest.raises(CompilerPanic, match="Mem2Var"):
        validate_pass_order([Mem2Var, MakeSSA], pipeline_name="test")

    with pytest.raises(CompilerPanic, match="Mem2Var"):
        validate_pass_order([MakeSSA, Mem2Var], pipeline_name="test")


def test_disable_simplify_cfg_fails_o2_pipeline_on_revert_constraint():
    with pytest.raises(CompilerPanic, match="RevertToAssert"):
        venom._build_fn_pass_pipeline(
            VenomOptimizationFlags(level=OptimizationLevel.O2, disable_simplify_cfg=True)
        )


def test_dft_requires_single_use_before_and_cfg_normalization_after():
    validate_pass_order([SingleUseExpansion, DFTPass, CFGNormalization], pipeline_name="test")
    validate_pass_order(
        [SingleUseExpansion, ReduceLiteralsCodesize, DFTPass, CFGNormalization],
        pipeline_name="test",
    )

    with pytest.raises(CompilerPanic, match="DFTPass"):
        validate_pass_order([DFTPass, CFGNormalization], pipeline_name="test")

    with pytest.raises(CompilerPanic, match="DFTPass"):
        validate_pass_order([SingleUseExpansion, DFTPass], pipeline_name="test")


def test_o2_dft_is_sandwiched_by_single_use_and_cfg_normalization():
    pipeline = venom._build_fn_pass_pipeline(VenomOptimizationFlags(level=OptimizationLevel.O2))
    pass_classes = [pass_cls for pass_cls, _ in pipeline]
    idx = pass_classes.index(DFTPass)

    assert pass_classes[idx - 1] is SingleUseExpansion
    assert pass_classes[idx + 1] is CFGNormalization


def test_error_message_stops_at_instead():
    class A(IRPass):
        pass

    class B(IRPass):
        pass

    class C(IRPass):
        pass

    class D(IRPass):
        required_immediate_successors = ("E",)

    class E(IRPass):
        pass

    with pytest.raises(CompilerPanic) as exc:
        validate_pass_order([A, B, C, D, C, E], pipeline_name="test")

    message = str(exc.value).splitlines()[0]
    assert message.endswith("instead.")
    assert "Pipeline context:" not in message

from typing import ClassVar, TypeAlias, Union

from vyper.venom.analysis import IRAnalysesCache
from vyper.venom.basicblock import IRLabel
from vyper.venom.context import IRContext
from vyper.venom.function import IRFunction
from vyper.venom.passes.machinery.inst_updater import InstUpdater

PassRef: TypeAlias = Union[str, type["IRPass"]]


def _resolve_label_chains(label_map: dict[IRLabel, IRLabel]) -> dict[IRLabel, IRLabel]:
    """
    Path-compress chained replacements, e.g. {a: b, b: c} -> {a: c, b: c},
    so that each label resolves to its final target in a single application
    of the map.
    """

    def _resolve(label: IRLabel) -> IRLabel:
        seen = set()
        while label in label_map:
            assert label not in seen, f"cycle in label map at {label}"
            seen.add(label)
            label = label_map[label]
        return label

    return {original: _resolve(replacement) for original, replacement in label_map.items()}


class IRPass:
    """
    Base class for all Venom IR passes.
    """

    function: IRFunction
    analyses_cache: IRAnalysesCache
    updater: InstUpdater  # optional, does not need to be instantiated
    # Order constraints for pass scheduling.
    # A tuple expresses acceptable alternatives. At least one must match.
    # - required_predecessors: passes that must appear before this pass.
    # - required_successors: passes that must appear after this pass.
    # - required_immediate_predecessors: pass immediately before this pass.
    # - required_immediate_successors: pass immediately after this pass.
    required_predecessors: ClassVar[tuple[PassRef, ...]] = ()
    required_successors: ClassVar[tuple[PassRef, ...]] = ()
    required_immediate_predecessors: ClassVar[tuple[PassRef, ...]] = ()
    required_immediate_successors: ClassVar[tuple[PassRef, ...]] = ()

    def __init__(self, analyses_cache: IRAnalysesCache, function: IRFunction):
        self.function = function
        self.analyses_cache = analyses_cache

    def _replace_all_labels(self, label_map: dict[IRLabel, IRLabel]) -> None:
        # the map may contain chains (e.g. {a: b, b: c}) when several
        # replacements are scheduled in one pass epoch; resolve them so a
        # single application of the map cannot leave dangling labels.
        label_map = _resolve_label_chains(label_map)

        for bb in self.function.get_basic_blocks():
            bb.replace_operands(label_map)

        # Also update labels in data segment.
        for data_section in self.function.ctx.data_segment:
            for item in data_section.data_items:
                data = item.data
                if isinstance(data, IRLabel) and data in label_map:
                    item.data = label_map[data]

    def run_pass(self, *args, **kwargs):
        raise NotImplementedError(f"Not implemented! {self.__class__}.run_pass()")


class IRGlobalPass:
    """
    Base class for all Venom IR passes.
    """

    ctx: IRContext
    analyses_caches: dict[IRFunction, IRAnalysesCache]

    def __init__(self, analyses_caches: dict[IRFunction, IRAnalysesCache], ctx: IRContext):
        self.analyses_caches = analyses_caches
        self.ctx = ctx

    def run_pass(self, *args, **kwargs):
        raise NotImplementedError(f"Not implemented! {self.__class__}.run_pass()")

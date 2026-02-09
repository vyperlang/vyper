from typing import ClassVar, TypeAlias, Union

from vyper.venom.analysis import IRAnalysesCache
from vyper.venom.context import IRContext
from vyper.venom.function import IRFunction
from vyper.venom.passes.machinery.inst_updater import InstUpdater

PassRef: TypeAlias = Union[str, type["IRPass"]]


class IRPass:
    """
    Base class for all Venom IR passes.
    """

    function: IRFunction
    analyses_cache: IRAnalysesCache
    updater: InstUpdater  # optional, does not need to be instantiated
    # Order constraints for pass scheduling.
    # A tuple expresses acceptable alternatives. At least one must match.
    must_run_before: ClassVar[tuple[PassRef, ...]] = ()
    must_run_after: ClassVar[tuple[PassRef, ...]] = ()
    must_run_immediately_before: ClassVar[tuple[PassRef, ...]] = ()
    must_run_immediately_after: ClassVar[tuple[PassRef, ...]] = ()

    def __init__(self, analyses_cache: IRAnalysesCache, function: IRFunction):
        self.function = function
        self.analyses_cache = analyses_cache

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

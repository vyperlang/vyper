from __future__ import annotations

from typing import TYPE_CHECKING, Type, TypeVar

if TYPE_CHECKING:
    from vyper.venom.context import IRContext
    from vyper.venom.function import IRFunction


class IRAnalysisBase:
    """
    Common base for all Venom IR analyses (per-function and global).
    """

    def analyze(self, *args, **kwargs):
        raise NotImplementedError

    def invalidate(self):
        pass


T = TypeVar("T", bound=IRAnalysisBase)


class IRAnalysis(IRAnalysisBase):
    """
    Base class for per-function Venom IR analyses.
    """

    function: IRFunction
    analyses_cache: IRAnalysesCache

    def __init__(self, analyses_cache: IRAnalysesCache, function: IRFunction):
        self.analyses_cache = analyses_cache
        self.function = function


class IRGlobalAnalysis(IRAnalysisBase):
    """
    Base class for analyses over the entire IR context.
    """

    ctx: IRContext
    global_analyses_cache: IRGlobalAnalysesCache

    def __init__(self, global_analyses_cache: IRGlobalAnalysesCache, ctx: IRContext):
        self.global_analyses_cache = global_analyses_cache
        self.ctx = ctx

    @property
    def analyses_caches(self) -> dict[IRFunction, IRAnalysesCache]:
        return self.global_analyses_cache.function_analyses_caches


GT = TypeVar("GT", bound=IRGlobalAnalysis)


class IRAnalysesCache:
    """
    A cache for IR analyses.
    """

    function: IRFunction
    analyses_cache: dict[Type[IRAnalysis], IRAnalysis]

    def __init__(self, function: IRFunction):
        self.analyses_cache = {}
        self.function = function

    def _ensure_global_analyses_cache(self) -> "IRGlobalAnalysesCache":
        global_cache = self.function.ctx.global_analyses_cache
        if global_cache is None:
            function_analyses_caches = {
                fn: IRAnalysesCache(fn) for fn in self.function.ctx.functions.values()
            }
            function_analyses_caches[self.function] = self
            global_cache = IRGlobalAnalysesCache(self.function.ctx, function_analyses_caches)
            self.function.ctx.global_analyses_cache = global_cache
            return global_cache

        for fn in self.function.ctx.functions.values():
            if fn not in global_cache.function_analyses_caches:
                global_cache.function_analyses_caches[fn] = IRAnalysesCache(fn)
        if self.function not in global_cache.function_analyses_caches:
            global_cache.function_analyses_caches[self.function] = self
        return global_cache

    def request_analysis(self, analysis_cls: Type[T], *args, **kwargs) -> T:
        """
        Request a specific analysis to be run on the IR. The result is cached and
        returned if the analysis has already been run.
        """
        if issubclass(analysis_cls, IRGlobalAnalysis):
            return self._ensure_global_analyses_cache().request_analysis(
                analysis_cls, *args, **kwargs
            )

        assert issubclass(analysis_cls, IRAnalysis), f"{analysis_cls} is not an IRAnalysis"
        if analysis_cls in self.analyses_cache:
            ret = self.analyses_cache[analysis_cls]
            assert isinstance(ret, analysis_cls)  # help mypy
            return ret

        analysis = analysis_cls(self, self.function)
        self.analyses_cache[analysis_cls] = analysis
        analysis.analyze(*args, **kwargs)

        return analysis

    def invalidate_analysis(self, analysis_cls: Type[IRAnalysisBase]):
        """
        Invalidate a specific analysis. This will remove the analysis from the cache.
        """
        if issubclass(analysis_cls, IRGlobalAnalysis):
            global_cache = self.function.ctx.global_analyses_cache
            if global_cache is not None:
                global_cache.invalidate_analysis(analysis_cls)
            return

        assert issubclass(analysis_cls, IRAnalysis), f"{analysis_cls} is not an IRAnalysis"
        analysis = self.analyses_cache.pop(analysis_cls, None)
        if analysis is not None:
            analysis.invalidate()

    def force_analysis(self, analysis_cls: Type[T], *args, **kwargs) -> T:
        """
        Force a specific analysis to be run on the IR even if it has already been run,
        and is cached.
        """
        if issubclass(analysis_cls, IRGlobalAnalysis):
            return self._ensure_global_analyses_cache().force_analysis(
                analysis_cls, *args, **kwargs
            )

        assert issubclass(analysis_cls, IRAnalysis), f"{analysis_cls} is not an IRAnalysis"
        if analysis_cls in self.analyses_cache:
            self.invalidate_analysis(analysis_cls)

        return self.request_analysis(analysis_cls, *args, **kwargs)


class IRGlobalAnalysesCache:
    """
    A cache for global IR analyses.
    """

    ctx: IRContext
    function_analyses_caches: dict[IRFunction, IRAnalysesCache]
    analyses_cache: dict[Type[IRGlobalAnalysis], IRGlobalAnalysis]

    def __init__(self, ctx: IRContext, function_analyses_caches: dict[IRFunction, IRAnalysesCache]):
        self.ctx = ctx
        self.function_analyses_caches = function_analyses_caches
        self.analyses_cache = {}

    def request_analysis(self, analysis_cls: Type[GT], *args, **kwargs) -> GT:
        assert issubclass(
            analysis_cls, IRGlobalAnalysis
        ), f"{analysis_cls} is not an IRGlobalAnalysis"
        if analysis_cls in self.analyses_cache:
            ret = self.analyses_cache[analysis_cls]
            assert isinstance(ret, analysis_cls)
            return ret

        analysis = analysis_cls(self, self.ctx)
        self.analyses_cache[analysis_cls] = analysis
        analysis.analyze(*args, **kwargs)
        return analysis

    def invalidate_analysis(self, analysis_cls: Type[IRGlobalAnalysis]):
        assert issubclass(
            analysis_cls, IRGlobalAnalysis
        ), f"{analysis_cls} is not an IRGlobalAnalysis"
        analysis = self.analyses_cache.pop(analysis_cls, None)
        if analysis is not None:
            analysis.invalidate()

    def force_analysis(self, analysis_cls: Type[GT], *args, **kwargs) -> GT:
        assert issubclass(
            analysis_cls, IRGlobalAnalysis
        ), f"{analysis_cls} is not an IRGlobalAnalysis"
        if analysis_cls in self.analyses_cache:
            self.invalidate_analysis(analysis_cls)

        return self.request_analysis(analysis_cls, *args, **kwargs)

from __future__ import annotations

from typing import TYPE_CHECKING, Type, TypeVar

from vyper.exceptions import CompilerPanic

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

    def __init__(self, function: IRFunction, *, isolated: bool = False):
        # Validators need fresh local analyses even when a pass missed an
        # invalidation. Such caches never participate in the shared registry.
        self.isolated = isolated
        self.analyses_cache = {}
        self.function = function

    def _ensure_global_analyses_cache(self) -> "IRGlobalAnalysesCache":
        if self.isolated:
            raise CompilerPanic("isolated caches cannot request global analyses")
        global_cache = self.function.ctx.global_analyses_cache
        if global_cache is None:
            global_cache = IRGlobalAnalysesCache(self.function.ctx, {self.function: self})
            self.function.ctx.global_analyses_cache = global_cache
        global_cache.register_function_cache(self)
        return global_cache

    def _canonical_cache(self) -> "IRAnalysesCache":
        if self.isolated:
            return self
        return self._ensure_global_analyses_cache().function_analyses_caches[self.function]

    def request_analysis(self, analysis_cls: Type[T], *args, **kwargs) -> T:
        """
        Request a specific analysis to be run on the IR. The result is cached and
        returned if the analysis has already been run.
        """
        if issubclass(analysis_cls, IRGlobalAnalysis):
            return self._ensure_global_analyses_cache().request_analysis(
                analysis_cls, *args, **kwargs
            )

        cache = self._canonical_cache()
        if cache is not self:
            return cache.request_analysis(analysis_cls, *args, **kwargs)

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
            if not self.isolated:
                self._ensure_global_analyses_cache().invalidate_analysis(analysis_cls)
            return

        cache = self._canonical_cache()
        if cache is not self:
            cache.invalidate_analysis(analysis_cls)
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

        cache = self._canonical_cache()
        if cache is not self:
            return cache.force_analysis(analysis_cls, *args, **kwargs)

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
        self._placeholders: set[IRFunction] = set()

    def register_function_cache(self, cache: IRAnalysesCache) -> None:
        """Fill missing entries without replacing an existing consumer's cache.

        Placeholder status belongs to this registry. An unused placeholder can
        be replaced; a populated one retains its analyses and invalidation hooks.
        Other caches for an already registered function delegate their requests
        and invalidations to its canonical cache instead of maintaining stale
        parallel analyses.
        """
        fn = cache.function
        registered = self.function_analyses_caches.get(fn)
        if registered is None:
            self.function_analyses_caches[fn] = cache
        elif registered is not cache and fn in self._placeholders:
            # Once populated, this cache owns invalidation hooks used by global
            # analyses. Keep it canonical and let the new consumer delegate.
            if not registered.analyses_cache:
                self.function_analyses_caches[fn] = cache
            self._placeholders.discard(fn)
        for fn in self.ctx.functions.values():
            if fn not in self.function_analyses_caches:
                self.function_analyses_caches[fn] = IRAnalysesCache(fn)
                self._placeholders.add(fn)

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

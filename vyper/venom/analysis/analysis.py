from __future__ import annotations

from typing import TYPE_CHECKING, Type, TypeVar

if TYPE_CHECKING:
    from vyper.venom.function import IRFunction


class IRAnalysis:
    """
    Base class for all Venom IR analyses.
    """

    function: IRFunction
    analyses_cache: IRAnalysesCache

    def __init__(self, analyses_cache: IRAnalysesCache, function: IRFunction):
        self.analyses_cache = analyses_cache
        self.function = function

    def analyze(self, *args, **kwargs):
        """
        Override this method to perform the analysis.
        """
        raise NotImplementedError

    def invalidate(self):
        """
        Override this method to respond to an invalidation request, and possibly
        invalidate any other analyses that depend on this one.
        """
        pass


T = TypeVar("T", bound=IRAnalysis)


class IRAnalysesCache:
    """
    A cache for IR analyses.
    """

    function: IRFunction
    analyses_cache: dict[Type[IRAnalysis], IRAnalysis]

    def __init__(self, function: IRFunction):
        self.analyses_cache = {}
        self.function = function

    # python3.12:
    #   def request_analysis[T](self, analysis_cls: Type[T], *args, **kwargs) -> T:
    def request_analysis(self, analysis_cls: Type[T], *args, **kwargs) -> T:
        """
        Request a specific analysis to be run on the IR. The result is cached and
        returned if the analysis has already been run.
        """
        assert issubclass(analysis_cls, IRAnalysis), f"{analysis_cls} is not an IRAnalysis"
        if analysis_cls in self.analyses_cache:
            ret = self.analyses_cache[analysis_cls]
            assert isinstance(ret, analysis_cls)  # help mypy
            return ret

        analysis = analysis_cls(self, self.function)
        self.analyses_cache[analysis_cls] = analysis
        analysis.analyze(*args, **kwargs)

        return analysis

    def invalidate_analysis(self, analysis_cls: Type[IRAnalysis]):
        """
        Invalidate a specific analysis. This will remove the analysis from the cache.
        """
        assert issubclass(analysis_cls, IRAnalysis), f"{analysis_cls} is not an IRAnalysis"
        analysis = self.analyses_cache.pop(analysis_cls, None)
        if analysis is not None:
            analysis.invalidate()

    def force_analysis(self, analysis_cls: Type[IRAnalysis], *args, **kwargs):
        """
        Force a specific analysis to be run on the IR even if it has already been run,
        and is cached.
        """
        assert issubclass(analysis_cls, IRAnalysis), f"{analysis_cls} is not an IRAnalysis"
        if analysis_cls in self.analyses_cache:
            self.invalidate_analysis(analysis_cls)

        return self.request_analysis(analysis_cls, *args, **kwargs)

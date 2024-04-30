from typing import Type

from vyper.venom.function import IRFunction


class IRPassManager:
    """
    Manages the analysis and passes for the Venom IR.
    """

    function: IRFunction
    valid_analyses: dict[Type["IRAnalysis"], "IRAnalysis"]  # type: ignore # noqa: F821

    def __init__(self, function: IRFunction):
        self.function = function
        self.valid_analyses = {}

    def request_analysis(
        self, analysis_cls: "IRAnalysis", *args, **kwargs  # type: ignore # noqa: F821
    ):
        """
        Request a specific analysis to be run on the IR. The result is cached and
        returned if the analysis has already been run.
        """
        from vyper.venom.analysis.analysis import IRAnalysis

        assert issubclass(analysis_cls, IRAnalysis), f"{analysis_cls} is not an IRAnalysis"
        if analysis_cls in self.valid_analyses:
            return self.valid_analyses[analysis_cls]
        analysis = analysis_cls(self)
        analysis.analyze(*args, **kwargs)

        self.valid_analyses[analysis] = analysis
        return analysis

    def invalidate_analysis(self, analysis_cls: "IRAnalysis"):  # type: ignore # noqa: F821
        """
        Invalidate a specific analysis. This will remove the analysis from the cache.
        """
        from vyper.venom.analysis.analysis import IRAnalysis

        assert issubclass(analysis_cls, IRAnalysis), f"{analysis_cls} is not an IRAnalysis"
        if analysis_cls not in self.valid_analyses:
            return
        self.valid_analyses[analysis_cls].invalidate()
        del self.valid_analyses[analysis_cls]

    def force_analysis(
        self, analysis_cls: "IRAnalysis", *args, **kwargs  # type: ignore # noqa: F821
    ):
        """
        Force a specific analysis to be run on the IR even if it has already been run,
        and is cached.
        """
        from vyper.venom.analysis.analysis import IRAnalysis

        assert issubclass(analysis_cls, IRAnalysis), f"{analysis_cls} is not an IRAnalysis"
        if analysis_cls in self.valid_analyses:
            self.invalidate_analysis(analysis_cls)
        return self.request_analysis(analysis_cls, *args, **kwargs)

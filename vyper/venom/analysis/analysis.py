from vyper.venom.passes.pass_manager import IRPassManager


class IRAnalysis:
    """
    Base class for all Venom IR analyses.
    """

    manager: IRPassManager

    def __init__(self, manager: IRPassManager):
        self.manager = manager

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
        raise NotImplementedError

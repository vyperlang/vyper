from typing import Optional

from vyper.compiler.settings import Settings, get_global_settings
from vyper.venom.analysis import IRAnalysesCache
from vyper.venom.context import IRContext
from vyper.venom.function import IRFunction


class IRPass:
    """
    Base class for all Venom IR passes.
    """

    function: IRFunction
    analyses_cache: IRAnalysesCache

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
    settings: Settings

    def __init__(
        self,
        analyses_caches: dict[IRFunction, IRAnalysesCache],
        ctx: IRContext,
        settings: Optional[Settings] = None,
    ):
        self.analyses_caches = analyses_caches
        self.ctx = ctx
        settings = settings or get_global_settings()
        self.settings = settings or Settings()

    def run_pass(self, *args, **kwargs):
        raise NotImplementedError(f"Not implemented! {self.__class__}.run_pass()")

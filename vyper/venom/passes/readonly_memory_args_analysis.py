from vyper.venom.analysis.readonly_memory_args import ReadonlyMemoryArgsAnalysis
from vyper.venom.passes.base_pass import IRGlobalPass


class ReadonlyMemoryArgsAnalysisPass(IRGlobalPass):
    """
    Apply readonly invoke-arg analysis results to IRFunction metadata.
    """

    def run_pass(self):
        readonly_idxs_by_fn = ReadonlyMemoryArgsAnalysis(self.analyses_caches, self.ctx).analyze()
        for fn, idxs in readonly_idxs_by_fn.items():
            fn._readonly_memory_invoke_arg_idxs = idxs

from vyper.venom.analysis.analysis import IRAnalysis

class AvailableExpressionAnalysis(IRAnalysis):
    def analyze(self, *args, **kwargs):
        return super().analyze(*args, **kwargs)

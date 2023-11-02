# REVIEW: can move this to `vyper/venom/passes/base_pass.py` or something


class IRPass:
    """
    Decorator for IR passes. This decorator will run the pass repeatedly
    until no more changes are made.
    """

    @classmethod
    def run_pass(cls, *args, **kwargs):
        t = cls()
        count = 0

        while True:
            changes = t._run_pass(*args, **kwargs) or 0
            if isinstance(changes, list):
                changes = len(changes)
            count += changes
            if changes == 0:
                break

        return count

    def _run_pass(self, *args, **kwargs):
        raise NotImplementedError(f"Not implemented! {self.__class__}.run_pass()")

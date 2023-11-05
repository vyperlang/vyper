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
            changes_count = t._run_pass(*args, **kwargs) or 0
            count += changes_count
            if changes_count == 0:
                break

        return count

    def _run_pass(self, *args, **kwargs):
        raise NotImplementedError(f"Not implemented! {self.__class__}.run_pass()")

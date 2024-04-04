class IRPass:
    """
    Decorator for IR passes. This decorator will run the pass repeatedly
    until no more changes are made.
    """

    def run_pass(self, *args, **kwargs):
        count = 0

        for _ in range(1000):
            changes_count = self._run_pass(*args, **kwargs) or 0
            count += changes_count
            if changes_count == 0:
                break
        else:
            raise Exception("Too many iterations in IR pass!", self.__class__)

        return count

    def _run_pass(self, *args, **kwargs):
        raise NotImplementedError(f"Not implemented! {self.__class__}.run_pass()")

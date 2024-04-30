from vyper.venom.passes.pass_manager import IRPassManager


class IRPass:
    """
    Base class for all Venom IR passes.
    """

    manager: IRPassManager

    def __init__(self, manager: IRPassManager):
        self.manager = manager

    def run_pass(self, *args, **kwargs):
        raise NotImplementedError(f"Not implemented! {self.__class__}.run_pass()")

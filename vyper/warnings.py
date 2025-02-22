import contextlib
import warnings
from typing import Optional

from vyper.exceptions import _BaseVyperException


class VyperWarning(_BaseVyperException, Warning):
    pass


# print a warning
def vyper_warn(warning: VyperWarning | str, node=None):
    if isinstance(warning, str):
        warning = VyperWarning(warning, node)
    warnings.warn(warning, stacklevel=2)


@contextlib.contextmanager
def warnings_filter(warnings_control: Optional[str]):
    # note: using warnings.catch_warnings() since it saves and restores
    # the warnings filter
    with warnings.catch_warnings():
        set_warnings_filter(warnings_control)
        yield


def set_warnings_filter(warnings_control: Optional[str]):
    if warnings_control == "error":
        warnings_filter = "error"
    elif warnings_control == "none":
        warnings_filter = "ignore"
    else:
        assert warnings_control is None  # sanity
        warnings_filter = "default"

    if warnings_control is not None:
        # warnings.simplefilter only adds to the warnings filters,
        # so we should clear warnings filter between calls to simplefilter()
        warnings.resetwarnings()

    # NOTE: in the future we can do more fine-grained control by setting
    # category to specific warning types
    warnings.simplefilter(warnings_filter, category=VyperWarning)  # type: ignore[arg-type]


class ContractSizeLimit(VyperWarning):
    """
    Warn if past the EIP-170 size limit
    """

    pass


class EnumUsage(VyperWarning):
    """
    Warn about using `enum` instead of `flag
    """

    pass


class Deprecation(VyperWarning):
    """
    General deprecation warning
    """

    pass

import warnings

from vyper.exceptions import _BaseVyperException


class VyperWarning(_BaseVyperException, Warning):
    pass


# print a warning
def vyper_warn(warning: VyperWarning | str, node=None):
    if isinstance(warning, str):
        warning = VyperWarning(warning, node)
    warnings.warn(warning, stacklevel=2)


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

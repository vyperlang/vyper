import enum


class DataLocation(enum.Enum):
    # TODO: rename me to something like VarLocation, or StorageRegion
    """
    Possible locations for variables in vyper
    """
    UNSET = enum.auto()  # like constants and stack variables
    MEMORY = enum.auto()  # local variables
    STORAGE = enum.auto()  # storage variables
    CALLDATA = enum.auto()  # arguments to external functions
    IMMUTABLES = enum.auto()  # immutable variables
    TRANSIENT = enum.auto()  # transient storage variables

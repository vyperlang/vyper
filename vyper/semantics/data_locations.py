import enum

from vyper.utils import StringEnum


class DataLocation(StringEnum):
    UNSET = enum.auto()
    MEMORY = enum.auto()
    STORAGE = enum.auto()
    CALLDATA = enum.auto()
    CODE = enum.auto()
    TRANSIENT = enum.auto()

import enum


class DataLocation(enum.Enum):
    UNSET = 0
    MEMORY = 1
    STORAGE = 2
    CALLDATA = 3
    CODE = 4


LOCATIONS = tuple(i for i in DataLocation if i != DataLocation.UNSET)

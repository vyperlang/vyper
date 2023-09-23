import enum


class DataLocation(enum.Enum):
    UNSET = 0
    MEMORY = 1
    STORAGE = 2
    CALLDATA = 3
    CODE = 4
    # XXX: needed for separate transient storage allocator
    # TRANSIENT = 5

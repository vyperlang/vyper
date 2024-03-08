def ceil32(n):
    return floor32(n + 31)


def floor32(n):
    return n & ~31


def to_int(stack_item) -> int:
    if isinstance(stack_item, int):
        return stack_item
    return int.from_bytes(stack_item, "big")


def to_bytes(stack_item) -> bytes:
    if isinstance(stack_item, bytes):
        return stack_item.rjust(32, b"\x00")
    return stack_item.to_bytes(32, "big")

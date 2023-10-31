from vyper.venom.basicblock import IRValueBase


class StackModel:
    NOT_IN_STACK = object()
    stack: list[IRValueBase]

    def __init__(self):
        self.stack = []

    def copy(self):
        new = StackModel()
        new.stack = self.stack.copy()
        return new

    def get_height(self) -> int:
        """
        Returns the height of the stack map.
        """
        return len(self.stack)

    def push(self, op: IRValueBase) -> None:
        """
        Pushes an operand onto the stack map.
        """
        assert isinstance(op, IRValueBase), f"push takes IRValueBase, got '{op}'"
        self.stack.append(op)

    def pop(self, num: int = 1) -> None:
        del self.stack[len(self.stack) - num :]

    def get_depth(self, op: IRValueBase) -> int:
        """
        Returns the depth of the first matching operand in the stack map.
        If the operand is not in the stack map, returns NOT_IN_STACK.
        """
        assert isinstance(op, IRValueBase), f"get_depth takes IRValueBase or list, got '{op}'"

        for i, stack_op in enumerate(reversed(self.stack)):
            if stack_op.value == op.value:
                return -i

        return StackModel.NOT_IN_STACK

    def get_shallowest_depth(self, ops: list[IRValueBase]) -> int:
        """
        Returns the depth of the first matching operand in the stack map.
        If the none of the operands in is `ops` is in the stack, returns NOT_IN_STACK.
        """
        assert isinstance(ops, list), f"get_shallowest_depth takes list, got '{ops}'"

        for i, stack_op in enumerate(reversed(self.stack)):
            if stack_op in ops:
                return -i

        return StackModel.NOT_IN_STACK

    def peek(self, depth: int) -> IRValueBase:
        """
        Returns the top of the stack map.
        """
        return self.stack[depth - 1]

    def poke(self, depth: int, op: IRValueBase) -> None:
        """
        Pokes an operand at the given depth in the stack map.
        """
        assert depth <= 0, "Bad depth"
        assert isinstance(op, IRValueBase), f"poke takes IRValueBase, got '{op}'"
        self.stack[depth - 1] = op

    def dup(self, assembly: list[str], depth: int) -> None:
        """
        Duplicates the operand at the given depth in the stack map.
        """
        assert depth <= 0, "Cannot dup positive depth"
        assembly.append(f"DUP{-(depth-1)}")
        self.stack.append(self.peek(depth))

    def swap(self, assembly: list[str], depth: int) -> None:
        """
        Swaps the operand at the given depth in the stack map with the top of the stack.
        """
        # convenience, avoids branching in caller
        if depth == 0:
            return

        assert depth < 0, "Cannot swap positive depth"
        assembly.append(f"SWAP{-depth}")
        top = self.stack[-1]
        self.stack[-1] = self.stack[depth - 1]
        self.stack[depth - 1] = top
    # REVIEW: maybe have a convenience function which swaps depth1 and depth2

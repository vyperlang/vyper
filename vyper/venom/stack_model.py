from vyper.venom.basicblock import IRValueBase, IRVariable


class StackModel:
    NOT_IN_STACK = object()
    # REVIEW: rename to `_stack_items` and add a `repr()` to StackModel
    # so that the stack is more hidden from observers
    _stack: list[IRValueBase]

    def __init__(self):
        self._stack = []

    def copy(self):
        new = StackModel()
        new._stack = self._stack.copy()
        return new

    @property
    def height(self) -> int:
        """
        Returns the height of the stack map.
        """
        return len(self._stack)

    def push(self, op: IRValueBase) -> None:
        """
        Pushes an operand onto the stack map.
        """
        assert isinstance(op, IRValueBase), f"push takes IRValueBase, got '{op}'"
        self._stack.append(op)

    def pop(self, num: int = 1) -> None:
        del self._stack[len(self._stack) - num :]

    def get_depth(self, op: IRValueBase) -> int:
        """
        Returns the depth of the first matching operand in the stack map.
        If the operand is not in the stack map, returns NOT_IN_STACK.
        """
        assert isinstance(op, IRValueBase), f"get_depth takes IRValueBase or list, got '{op}'"

        for i, stack_op in enumerate(reversed(self._stack)):
            if stack_op.value == op.value:
                return -i

        return StackModel.NOT_IN_STACK

    def get_phi_depth(self, phi1: IRVariable, phi2: IRVariable) -> int:
        """
        Returns the depth of the first matching phi variable in the stack map.
        If the none of the phi operands are in the stack, returns NOT_IN_STACK.
        Asserts that exactly one of phi1 and phi2 is found.
        """
        assert isinstance(phi1, IRVariable)
        assert isinstance(phi2, IRVariable)

        ret = StackModel.NOT_IN_STACK
        for i, stack_item in enumerate(reversed(self._stack)):
            if stack_item in (phi1, phi2):
                assert (
                    ret is StackModel.NOT_IN_STACK
                ), f"phi argument is not unique! {phi1}, {phi2}, {self._stack}"
                ret = -i

        return ret

    def peek(self, depth: int) -> IRValueBase:
        """
        Returns the top of the stack map.
        """
        assert depth is not StackModel.NOT_IN_STACK, "Cannot peek non-in-stack depth"
        return self._stack[depth - 1]

    def poke(self, depth: int, op: IRValueBase) -> None:
        """
        Pokes an operand at the given depth in the stack map.
        """
        assert depth is not StackModel.NOT_IN_STACK, "Cannot poke non-in-stack depth"
        assert depth <= 0, "Bad depth"
        assert isinstance(op, IRValueBase), f"poke takes IRValueBase, got '{op}'"
        self._stack[depth - 1] = op

    def dup(self, depth: int) -> None:
        """
        Duplicates the operand at the given depth in the stack map.
        """
        assert depth is not StackModel.NOT_IN_STACK, "Cannot dup non-existent operand"
        assert depth <= 0, "Cannot dup positive depth"
        self._stack.append(self.peek(depth))

    def swap(self, depth: int) -> None:
        """
        Swaps the operand at the given depth in the stack map with the top of the stack.
        """
        assert depth is not StackModel.NOT_IN_STACK, "Cannot swap non-existent operand"
        assert depth < 0, "Cannot swap positive depth"
        top = self._stack[-1]
        self._stack[-1] = self._stack[depth - 1]
        self._stack[depth - 1] = top

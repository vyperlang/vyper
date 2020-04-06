from vyper.exceptions import (
    InvalidOperation,
    VyperException,
)


class UnionType(set):
    """
    Set subclass for literal values where the final type is not yet determined.

    When this object is compared to another type, invalid types for the comparison
    are removed. For example, the literal `1` is initially a `UnionType` of
    `{int128, uint256}`. If the type is then compared to `-1` it is considered to
    be `int128` and subsequent comparisons to `uint256` will return `False`.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._locked = False

    def __str__(self):
        if len(self) == 1:
            return str(next(iter(self)))
        return f"{{{', '.join([str(i) for i in self])}}}"

    @property
    def length(self):
        return min(i.length for i in self)

    def _compare_type(self, other):
        if not isinstance(other, UnionType):
            other = [other]

        matches = [i for i in self if any(i._compare_type(x) for x in other)]
        if not matches:
            return False

        if not self._locked:
            self.intersection_update(matches)
        return True

    def _validate(self, node, attr):
        for typ in list(self):
            fn = getattr(typ, attr, None)
            if fn:
                try:
                    fn(node)
                    continue
                except VyperException:
                    pass
            self.remove(typ)
        if not self:
            raise InvalidOperation("Invalid operation for type", node)

    def validate_comparator(self, node):
        self._validate(node, 'validate_comparator')

    def validate_boolean_op(self, node):
        self._validate(node, 'validate_boolean_op')

    def validate_numeric_op(self, node):
        self._validate(node, 'validate_numeric_op')

    def lock(self):
        """
        Locks the type.

        A locked UnionType maintains it's potential types after comparison. This
        is useful for builtin function arguments.
        """
        self._locked = True

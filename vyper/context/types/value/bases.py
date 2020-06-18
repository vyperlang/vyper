from collections import OrderedDict

from vyper.context.types.bases import BaseType
from vyper.exceptions import NamespaceCollision, UnknownAttribute


class ValueType(BaseType):
    """
    Base class for types representing a single value.

    Class attributes
    ----------------
    _valid_literal: VyperNode | Tuple
        A vyper ast class or tuple of ast classes that can represent valid literals
        for the given type. Including this attribute will allow literal values to be
        cast as this type.
    """

    def __repr__(self):
        return self._id

    def get_signature(self):
        return (), self


class MemberType(ValueType):
    """
    Base class for types that have accessible members.

    Class attributes
    ----------------
    _type_members : Dict[str, BaseType]
        Dictionary of members common to all values of this type.

    Object attributes
    -----------------
    members : OrderedDict[str, BaseType]
        Dictionary of members for the given type.
    """

    def __init__(self, is_constant: bool = False, is_public: bool = False) -> None:
        super().__init__(is_constant, is_public)
        self.members = OrderedDict()

    def add_member(self, name, type_):
        if name in self.members:
            raise NamespaceCollision(f"Member {name} already exists in {self}")
        if name in getattr(self, "_type_members", []):
            raise NamespaceCollision(f"Member {name} already exists in {self}")
        self.members[name] = type_

    def get_member(self, key, node):
        if key in self.members:
            return self.members[key]
        if key in getattr(self, "_type_members", []):
            return self._type_members[key]
        raise UnknownAttribute(f"{self} has no member '{key}'", node)

    def __repr__(self):
        return f"{self._id}"

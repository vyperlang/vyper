
class Unit:
    """
    A unit object.

    Units can be applied to types that implement the `unit` member. They allow
    users to apply custom subtypes to the builtin vyper types.

    Object attributes
    -----------------
    name : str
        The short-form symbol used to represent the type within a contract.

    description : str
        A verbose description for the type.
    """
    __slots__ = ("description", "name",)

    def __init__(self, name: str, description: str):
        self.name = name
        self.description = description

    def __str__(self):
        return self.name

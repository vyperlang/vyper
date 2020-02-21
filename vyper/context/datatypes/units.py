
class Unit:

    # TODO docs

    __slots__ = ("description", "name", "enclosing_scope")

    def __init__(self, name: str, description: str, enclosing_scope: str):
        self.name = name
        self.description = description
        self.enclosing_scope = enclosing_scope

    def __str__(self):
        return self.name

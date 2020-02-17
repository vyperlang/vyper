
class Unit:

    # TODO docs

    __slots__ = ("description", "name")

    def __init__(self, name: str, description: str):
        self.name = name
        self.description = description

    def __str__(self):
        return self.name

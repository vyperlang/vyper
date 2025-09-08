class Label:
    def __init__(self, label: str):
        assert isinstance(label, str)
        self.label = label

    def __repr__(self):
        return f"LABEL {self.label}"

    def __eq__(self, other):
        if not isinstance(other, Label):
            return False
        return self.label == other.label

    def __hash__(self):
        return hash(self.label)
    
def is_label(i):
    return isinstance(i, Label)
    
# this could be fused with Label, the only difference is if
# it gets looked up from const_map or symbol_map.
class CONSTREF:
    def __init__(self, label: str):
        assert isinstance(label, str)
        self.label = label

    def __repr__(self):
        return f"CONSTREF {self.label}"

    def __eq__(self, other):
        if not isinstance(other, CONSTREF):
            return False
        return self.label == other.label

    def __hash__(self):
        return hash(self.label)

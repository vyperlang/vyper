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


SymbolKey = Label | CONSTREF


class CONST:
    def __init__(self, name: str, value: int):
        assert isinstance(name, str)
        assert isinstance(value, int)
        self.name = name
        self.value = value

    def __repr__(self):
        return f"CONST {self.name} {self.value}"

    def __eq__(self, other):
        if not isinstance(other, CONST):
            return False
        return self.name == other.name and self.value == other.value


class BaseConstOp:
    def __init__(self, name: str, op1: str | int, op2: str | int):
        assert isinstance(name, str)
        assert isinstance(op1, (str, int))
        assert isinstance(op2, (str, int))
        self.name = name
        self.op1 = op1
        self.op2 = op2

    def __eq__(self, other):
        if not isinstance(other, type(self)):
            return False
        return self.name == other.name and self.op1 == other.op1 and self.op2 == other.op2

    def _resolve_operand(self, operand: str | int, symbol_map: dict[SymbolKey, int]) -> int | None:
        if isinstance(operand, str):
            # Handle @ prefix for label references
            if operand.startswith("@"):
                label_name = operand[1:]
                label = Label(label_name)
                if label in symbol_map:
                    return symbol_map[label]
            else:
                # Try as CONSTREF first
                op_ref = CONSTREF(operand)
                if op_ref in symbol_map:
                    return symbol_map[op_ref]
                # Try as Label
                label = Label(operand)
                if label in symbol_map:
                    return symbol_map[label]
        elif isinstance(operand, int):
            return operand
        return None

    def calculate(self, symbol_map: dict[SymbolKey, int]) -> int | None:
        op1_val = self._resolve_operand(self.op1, symbol_map)
        op2_val = self._resolve_operand(self.op2, symbol_map)

        if op1_val is not None and op2_val is not None:
            return self._apply_operation(op1_val, op2_val)
        return None

    def _apply_operation(self, op1_val: int, op2_val: int) -> int:
        raise NotImplementedError("Subclasses must implement _apply_operation")


class CONST_ADD(BaseConstOp):
    def __repr__(self):
        return f"CONST_ADD {self.name} {self.op1} {self.op2}"

    def _apply_operation(self, op1_val: int, op2_val: int) -> int:
        return op1_val + op2_val


class CONST_SUB(BaseConstOp):
    def __repr__(self):
        return f"CONST_SUB {self.name} {self.op1} {self.op2}"

    def _apply_operation(self, op1_val: int, op2_val: int) -> int:
        return op1_val - op2_val


class CONST_MAX(BaseConstOp):
    def __repr__(self):
        return f"CONST_MAX {self.name} {self.op1} {self.op2}"

    def _apply_operation(self, op1_val: int, op2_val: int) -> int:
        return max(op1_val, op2_val)

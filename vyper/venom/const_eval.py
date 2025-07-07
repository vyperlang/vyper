"""
Constant expression evaluator for Venom IR.

Supports simple expressions with function-style notation:
- Literals: 123, 0x100
- Constant references: $CONST_NAME
- Label references: @label_name
- Operations: add(a, b), sub(a, b), mul(a, b), div(a, b), mod(a, b), max(a, b), min(a, b)
"""
from typing import Any, Union

from vyper.exceptions import CompilerPanic
from vyper.venom.basicblock import IRLabel, IRLiteral


class ConstEvalException(CompilerPanic):
    pass


_const_label_counter = 0


def generate_const_label_name() -> str:
    """Generate a unique label name for an unresolved constant."""
    global _const_label_counter
    label = f"__const_{_const_label_counter}"
    _const_label_counter += 1
    return label


def evaluate_const_expr(expr: Any, constants: dict[str, int], global_labels: dict[str, int]) -> int:
    # Handle simple cases first
    if isinstance(expr, int):
        return expr

    if isinstance(expr, IRLiteral):
        return expr.value

    if isinstance(expr, IRLabel):
        # Handle IRLabel objects
        label_name = expr.value
        if label_name not in global_labels:
            raise ConstEvalException(f"Undefined global label: {label_name}")
        return global_labels[label_name]

    if isinstance(expr, str):
        # Check if it's a constant reference ($NAME)
        if expr.startswith("$"):
            const_name = expr[1:]
            if const_name not in constants:
                raise ConstEvalException(f"Undefined constant: {const_name}")
            return constants[const_name]

        # Check if it's a label reference (@NAME)
        if expr.startswith("@"):
            label_name = expr[1:]
            if label_name not in global_labels:
                raise ConstEvalException(f"Undefined global label: {label_name}")
            return global_labels[label_name]

        # Otherwise it might be a plain identifier (shouldn't happen in well-formed expressions)
        raise ConstEvalException(f"Invalid constant expression: {expr}")

    # Handle function-style operations
    if isinstance(expr, tuple) and len(expr) == 3:
        op_name, arg1, arg2 = expr

        # Recursively evaluate arguments
        val1 = evaluate_const_expr(arg1, constants, global_labels)
        val2 = evaluate_const_expr(arg2, constants, global_labels)

        # Perform operation
        if op_name == "add":
            return val1 + val2
        elif op_name == "sub":
            return val1 - val2
        elif op_name == "mul":
            return val1 * val2
        elif op_name == "div":
            if val2 == 0:
                raise ConstEvalException("Division by zero in const expression")
            return val1 // val2  # Integer division
        elif op_name == "mod":
            if val2 == 0:
                raise ConstEvalException("Modulo by zero in const expression")
            return val1 % val2
        elif op_name == "max":
            return max(val1, val2)
        elif op_name == "min":
            return min(val1, val2)
        else:
            raise ConstEvalException(f"Unknown operation: {op_name}")

    raise ConstEvalException(f"Invalid constant expression format: {expr}")


def try_evaluate_const_expr(
    expr: Any,
    constants: dict[str, int],
    global_labels: dict[str, int],
    unresolved_consts: dict[str, Any],
    const_refs: set[str],
) -> Union[int, str]:
    # Handle simple cases first
    if isinstance(expr, int):
        return expr

    if isinstance(expr, IRLiteral):
        return expr.value

    if isinstance(expr, IRLabel):
        # Handle IRLabel objects
        label_name = expr.value
        if label_name in global_labels:
            # Label is already defined, return its value
            return global_labels[label_name]
        else:
            # Label is unresolved
            const_refs.add(label_name)
            if label_name not in unresolved_consts:
                unresolved_consts[label_name] = ("ref", label_name)
            return label_name

    if isinstance(expr, str):
        # Check if it's a constant reference ($NAME)
        if expr.startswith("$"):
            const_name = expr[1:]
            if const_name not in constants:
                # Use the constant name directly as the label for simple references
                const_refs.add(const_name)
                if const_name not in unresolved_consts:
                    unresolved_consts[const_name] = ("ref", const_name)
                return const_name
            return constants[const_name]

        # Check if it's a label reference (@NAME)
        if expr.startswith("@"):
            label_name = expr[1:]
            # Always treat label references as unresolved so they remain as labels
            const_refs.add(label_name)
            if label_name not in unresolved_consts:
                unresolved_consts[label_name] = ("ref", label_name)
            return label_name

        # Otherwise it might be a plain identifier
        raise ConstEvalException(f"Invalid constant expression: {expr}")

    # Handle operations
    if isinstance(expr, tuple) and len(expr) == 3:
        op_name, arg1, arg2 = expr

        # Recursively evaluate arguments
        val1 = try_evaluate_const_expr(
            arg1, constants, global_labels, unresolved_consts, const_refs
        )
        val2 = try_evaluate_const_expr(
            arg2, constants, global_labels, unresolved_consts, const_refs
        )

        # If both values are integers, we can compute the result
        if isinstance(val1, int) and isinstance(val2, int):
            # Perform operation
            if op_name == "add":
                return val1 + val2
            elif op_name == "sub":
                return val1 - val2
            elif op_name == "mul":
                return val1 * val2
            elif op_name == "div":
                if val2 == 0:
                    raise ConstEvalException("Division by zero in const expression")
                return val1 // val2
            elif op_name == "mod":
                if val2 == 0:
                    raise ConstEvalException("Modulo by zero in const expression")
                return val1 % val2
            elif op_name == "max":
                return max(val1, val2)
            elif op_name == "min":
                return min(val1, val2)
            else:
                raise ConstEvalException(f"Unknown operation: {op_name}")

        # Otherwise, create a label for this unresolved expression
        label = generate_const_label_name()
        unresolved_consts[label] = (op_name, val1, val2)
        return label

    raise ConstEvalException(f"Invalid constant expression format: {expr}")

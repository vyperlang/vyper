import types

from vyper.settings import (
    VYPER_ERROR_CONTEXT_LINES,
    VYPER_ERROR_LINE_NUMBERS,
)


class VyperException(Exception):
    """
    Base Vyper exception class.

    This exception is not raised directly. Other exceptions inherit it in
    order to display source annotations in the error string.
    """
    def __init__(self, message='Error Message not found.', item=None):
        self.message = message
        self.lineno = None
        self.col_offset = None

        if isinstance(item, tuple):  # is a position.
            self.lineno, self.col_offset = item[:2]
        elif item and hasattr(item, 'lineno'):
            self.set_err_pos(item.lineno, item.col_offset)
            if hasattr(item, 'full_source_code'):
                self.source_code = item.full_source_code

    def set_err_pos(self, lineno, col_offset):
        if not self.lineno:
            self.lineno = lineno

            if not self.col_offset:
                self.col_offset = col_offset

    def __str__(self):
        lineno, col_offset = self.lineno, self.col_offset

        if lineno is not None and hasattr(self, 'source_code'):
            from vyper.utils import annotate_source_code

            source_annotation = annotate_source_code(
                self.source_code,
                lineno,
                col_offset,
                context_lines=VYPER_ERROR_CONTEXT_LINES,
                line_numbers=VYPER_ERROR_LINE_NUMBERS,
            )
            col_offset_str = '' if col_offset is None else str(col_offset)
            return f'line {lineno}:{col_offset_str} {self.message}\n{source_annotation}'

        elif lineno is not None and col_offset is not None:
            return f'line {lineno}:{col_offset} {self.message}'

        return self.message


class SyntaxException(VyperException):

    """Invalid syntax."""

    def __init__(self, message, source_code, lineno, col_offset):
        item = types.SimpleNamespace()  # TODO: Create an actual object for this
        item.lineno = lineno
        item.col_offset = col_offset
        item.full_source_code = source_code
        super().__init__(message, item)


class StructureException(VyperException):
    """Invalid structure for parsable syntax."""


class VersionException(VyperException):
    """Version string is malformed or incompatible with this compiler version."""


class InvalidLiteralException(VyperException):
    """Invalid literal value."""


class VariableDeclarationException(VyperException):
    """Invalid variable declaration."""


class FunctionDeclarationException(VyperException):
    """Invalid function declaration."""


class EventDeclarationException(VyperException):
    """Invalid event declaration."""


class UndeclaredDefinition(VyperException):
    """Reference to a definition that has not been declared."""


class NamespaceCollision(VyperException):
    """Assignment to a name that is already in use."""


class InvalidAttribute(VyperException):
    """Reference to an attribute that does not exist."""


class InvalidReference(VyperException):
    """Invalid reference to an existing definition."""


class InvalidOperation(VyperException):
    """Invalid operator for a given type."""


class InvalidTypeException(VyperException):
    """Type is invalid for an action."""


class TypeMismatchException(VyperException):
    """Attempt to perform an action between multiple objects of incompatible types."""


class ArgumentException(VyperException):
    """Call to a function with invalid arguments."""


class CallViolation(VyperException):
    """Illegal function call."""


class ConstancyViolationException(VyperException):
    """State-changing action in a constant context."""


class NonPayableViolationException(VyperException):
    """msg.value in a nonpayable function."""


class InterfaceViolation(VyperException):
    """Interface is not fully implemented."""


class ArrayIndexException(VyperException):
    """Array index out of range."""


class ZeroDivisionException(VyperException):
    """Second argument to a division or modulo operation was zero."""


class OverflowException(VyperException):
    """Numeric value out of range for the given type."""


class EvmVersionException(VyperException):
    """Invalid action for the active EVM ruleset."""


class CompilerPanic(Exception):

    """Unexpected error during compilation."""

    def __init__(self, message):
        self.message = message

    def __str__(self):
        return self.message + ' Please create an issue.'


class JSONError(Exception):

    """Invalid compiler input JSON."""

    def __init__(self, msg, lineno=None, col_offset=None):
        super().__init__(msg)
        self.lineno = lineno
        self.col_offset = col_offset


class ParserException(Exception):
    """Contract source cannot be parsed."""

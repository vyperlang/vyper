import copy
import types

from vyper.settings import VYPER_ERROR_CONTEXT_LINES, VYPER_ERROR_LINE_NUMBERS


class ExceptionList(list):
    """
    List subclass for storing exceptions.
    To deliver multiple compilation errors to the user at once, append each
    raised Exception to this list and call raise_if_not_empty once the task
    is completed.
    """
    def raise_if_not_empty(self):
        if len(self) == 1:
            raise self[0]
        elif len(self) > 1:
            if len(set(type(i) for i in self)) > 1:
                err_type = StructureException
            else:
                err_type = type(self[0])
            err_msg = ["Compilation failed with the following errors:"]
            err_msg += [f"{type(i).__name__}: {i}" for i in self]
            raise err_type("\n\n".join(err_msg))


class VyperException(Exception):
    """
    Base Vyper exception class.

    This exception is not raised directly. Other exceptions inherit it in
    order to display source annotations in the error string.
    """
    def __init__(self, message='Error Message not found.', item=None):
        """
        Exception initializer.

        Arguments
        ---------
        message : str
            Error message to display with the exception.
        item : VyperNode | tuple, optional
            Vyper ast node or tuple of (lineno, col_offset) indicating where
            the exception occured.
        """
        self.message = message
        self.lineno = None
        self.col_offset = None

        if isinstance(item, tuple):
            self.lineno, self.col_offset = item[:2]
        elif hasattr(item, 'lineno'):
            self.lineno = item.lineno
            self.col_offset = item.col_offset
            self.source_code = item.full_source_code

    def with_annotation(self, node):
        """
        Creates a copy of this exception with a modified source annotation.

        Arguments
        ---------
        node : VyperNode
            AST node to obtain the source offset from.

        Returns
        -------
        A copy of the exception with the new offset applied.
        """
        exc = copy.copy(self)
        exc.lineno = node.lineno
        exc.col_offset = node.col_offset
        exc.source_code = node.full_source_code
        return exc

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


class NatSpecSyntaxException(SyntaxException):
    """Invalid syntax within NatSpec docstring."""


class StructureException(VyperException):
    """Invalid structure for parsable syntax."""


class VersionException(VyperException):
    """Version string is malformed or incompatible with this compiler version."""


class VariableDeclarationException(VyperException):
    """Invalid variable declaration."""


class FunctionDeclarationException(VyperException):
    """Invalid function declaration."""


class EventDeclarationException(VyperException):
    """Invalid event declaration."""


class UnknownType(VyperException):
    """Reference to a type that does not exist."""


class UnknownAttribute(VyperException):
    """Reference to an attribute that does not exist."""


class UndeclaredDefinition(VyperException):
    """Reference to a definition that has not been declared."""


class NamespaceCollision(VyperException):
    """Assignment to a name that is already in use."""


class InvalidLiteral(VyperException):
    """Invalid literal value."""


class InvalidAttribute(VyperException):
    """Reference to an attribute that does not exist."""


class InvalidReference(VyperException):
    """Invalid reference to an existing definition."""


class InvalidOperation(VyperException):
    """Invalid operator for a given type."""


class InvalidType(VyperException):
    """Type is invalid for an action."""


class TypeMismatch(VyperException):
    """Attempt to perform an action between multiple objects of incompatible types."""


class ArgumentException(VyperException):
    """Call to a function with invalid arguments."""


class CallViolation(VyperException):
    """Illegal function call."""


class ConstancyViolation(VyperException):
    """State-changing action in a constant context."""


class NonPayableViolation(VyperException):
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


class JSONError(Exception):

    """Invalid compiler input JSON."""

    def __init__(self, msg, lineno=None, col_offset=None):
        super().__init__(msg)
        self.lineno = lineno
        self.col_offset = col_offset


class ParserException(Exception):
    """Contract source cannot be parsed."""


class VyperInternalException(Exception):
    """
    Base Vyper internal exception class.

    This exception is not raised directly, it is subclassed by other internal
    exceptions.

    Internal exceptions are raised as a means of passing information between
    compiler processes. They should never be exposed to the user.
    """
    def __init__(self, message=""):
        self.message = message

    def __str__(self):
        return (
            f"{self.message}\n\nThis is an unhandled internal compiler error. "
            "Please create an issue on Github to notify the developers.\n"
            "https://github.com/vyperlang/vyper/issues/new?template=bug.md"
        )


class CompilerPanic(VyperInternalException):
    """General unexpected error during compilation."""


class UnexpectedNodeType(VyperInternalException):
    """Unexpected AST node type."""


class UnexpectedValue(VyperInternalException):
    """Unexpected Value."""


class UnfoldableNode(VyperInternalException):
    """Constant folding logic cannot be applied to an AST node."""

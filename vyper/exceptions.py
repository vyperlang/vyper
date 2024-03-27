import contextlib
import copy
import textwrap
import types

from vyper.compiler.settings import VYPER_ERROR_CONTEXT_LINES, VYPER_ERROR_LINE_NUMBERS


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
            err_msg = ["Compilation failed with the following errors:"]
            err_msg += [f"{type(i).__name__}: {i}" for i in reversed(self)]
            raise VyperException("\n\n".join(err_msg))


class _BaseVyperException(Exception):
    """
    Base Vyper exception class.

    This exception is not raised directly. Other exceptions inherit it in
    order to display source annotations in the error string.
    """

    def __init__(self, message="Error Message not found.", *items, hint=None, prev_decl=None):
        """
        Exception initializer.

        Arguments
        ---------
        message : str
            Error message to display with the exception.
        *items : VyperNode | Tuple[str, VyperNode], optional
            Vyper ast node(s), or tuple of (description, node) indicating where
            the exception occurred. Source annotations are generated in the order
            the nodes are given.

            A single tuple of (lineno, col_offset) is also understood to support
            the old API, but new exceptions should not use this approach.
        """
        self._message = message
        self._hint = hint
        self.prev_decl = prev_decl

        self.lineno = None
        self.col_offset = None
        self.annotations = None

        if len(items) == 1 and isinstance(items[0], tuple) and isinstance(items[0][0], int):
            # support older exceptions that don't annotate - remove this in the future!
            self.lineno, self.col_offset = items[0][:2]
        else:
            # strip out None sources so that None can be passed as a valid
            # annotation (in case it is only available optionally)
            self.annotations = [k for k in items if k is not None]

    def with_annotation(self, *annotations):
        """
        Creates a copy of this exception with a modified source annotation.

        Arguments
        ---------
        *annotations : VyperNode | Tuple[str, VyperNode]
            AST node(s), or tuple of (description, node) to use in the annotation.

        Returns
        -------
        A copy of the exception with the new node offset(s) applied.
        """
        exc = copy.copy(self)
        exc.annotations = annotations
        return exc

    def append_annotation(self, exc):
        if self.annotations is None:
            self.annotations = []

        self.annotations = [exc] + self.annotations

    @property
    def hint(self):
        # some hints are expensive to compute, so we wait until the last
        # minute when the formatted message is actually requested to compute
        # them.
        if callable(self._hint):
            return self._hint()
        return self._hint

    @property
    def message(self):
        msg = self._message
        if self.hint:
            msg += f"\n\n  (hint: {self.hint})"
        return msg

    def format_annotation(self, value):
        from vyper import ast as vy_ast
        from vyper.utils import annotate_source_code

        node = value[1] if isinstance(value, tuple) else value
        node_msg = ""

        if isinstance(node, vy_ast.VyperNode):
            # folded AST nodes contain pointers to the original source
            node = node.get_original_node()

        try:
            source_annotation = annotate_source_code(
                # add trailing space because EOF exceptions point one char beyond the length
                f"{node.full_source_code} ",
                node.lineno,
                node.col_offset,
                context_lines=VYPER_ERROR_CONTEXT_LINES,
                line_numbers=VYPER_ERROR_LINE_NUMBERS,
            )
        except Exception:
            # necessary for certain types of syntax exceptions
            return None

        if isinstance(node, vy_ast.VyperNode):
            module_node = node.get_ancestor(vy_ast.Module)

            if module_node.get("path") not in (None, "<unknown>"):
                node_msg = f'{node_msg}contract "{module_node.path}:{node.lineno}", '

            fn_node = node.get_ancestor(vy_ast.FunctionDef)
            if fn_node:
                node_msg = f'{node_msg}function "{fn_node.name}", '

        col_offset_str = "" if node.col_offset is None else str(node.col_offset)
        node_msg = f"{node_msg}line {node.lineno}:{col_offset_str} \n{source_annotation}\n"

        if isinstance(value, tuple):
            # if annotation includes a message, apply it at the start and further indent
            node_msg = textwrap.indent(node_msg, "  ")
            node_msg = f"{value[0]}\n{node_msg}"

        node_msg = textwrap.indent(node_msg, "  ")
        return node_msg

    def __str__(self):
        if not self.annotations:
            if self.lineno is not None and self.col_offset is not None:
                return f"line {self.lineno}:{self.col_offset} {self.message}"
            else:
                return self.message

        annotation_list = []

        if self.prev_decl is not None:
            formatted_decl = self.format_annotation(self.prev_decl)
            formatted_decl = f" (previously declared at):\n{formatted_decl}"
            annotation_list.append(formatted_decl)

        for value in self.annotations:
            annotation_list.append(self.format_annotation(value))

        annotation_list = [s for s in annotation_list if s is not None]
        annotation_msg = "\n".join(annotation_list)
        return f"{self.message}\n\n{annotation_msg}"


class VyperException(_BaseVyperException):
    pass


class SyntaxException(VyperException):

    """Invalid syntax."""

    def __init__(self, message, source_code, lineno, col_offset):
        item = types.SimpleNamespace()  # TODO: Create an actual object for this
        item.lineno = lineno
        item.col_offset = col_offset
        item.full_source_code = source_code
        super().__init__(message, item)


class DecimalOverrideException(VyperException):
    """The Vyper compiler uses specific Decimal settings which
    if overridden could lead to incorrect behavior.
    """


class NatSpecSyntaxException(SyntaxException):
    """Invalid syntax within NatSpec docstring."""


class StructureException(VyperException):
    """Invalid structure for parsable syntax."""


class InstantiationException(StructureException):
    """Variable or expression cannot be instantiated"""


class VersionException(VyperException):
    """Version string is malformed or incompatible with this compiler version."""


class VariableDeclarationException(VyperException):
    """Invalid variable declaration."""


class FunctionDeclarationException(VyperException):
    """Invalid function declaration."""


class FlagDeclarationException(VyperException):
    """Invalid flag declaration."""


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


class ImportCycle(VyperException):
    """An import cycle"""


class DuplicateImport(VyperException):
    """A module was imported twice from the same module"""


class ModuleNotFound(VyperException):
    """Module was not found"""


class ImmutableViolation(VyperException):
    """Modifying an immutable variable, constant, or definition."""


class InitializerException(VyperException):
    """An issue with initializing/constructing a module"""


class BorrowException(VyperException):
    """An issue with borrowing/using a module"""


class StateAccessViolation(VyperException):
    """Violating the mutability of a function definition."""


class NonPayableViolation(VyperException):
    """msg.value in a nonpayable function."""


class InterfaceViolation(VyperException):
    """Interface is not fully implemented."""


class IteratorException(VyperException):
    """Improper use of iterators."""


class ArrayIndexException(VyperException):
    """Array index out of range."""


class ZeroDivisionException(VyperException):
    """Second argument to a division or modulo operation was zero."""


class OverflowException(VyperException):
    """Numeric value out of range for the given type."""


class EvmVersionException(VyperException):
    """Invalid action for the active EVM ruleset."""


class StorageLayoutException(VyperException):
    """Invalid slot for the storage layout overrides"""


class MemoryAllocationException(VyperException):
    """Tried to allocate too much memory"""


class JSONError(Exception):

    """Invalid compiler input JSON."""

    def __init__(self, msg, lineno=None, col_offset=None):
        super().__init__(msg)
        self.lineno = lineno
        self.col_offset = col_offset


class ParserException(Exception):
    """Contract source cannot be parsed."""


class UnimplementedException(VyperException):
    """Some feature is known to be not implemented"""


class StaticAssertionException(VyperException):
    """An assertion is proven to fail at compile-time."""


class VyperInternalException(_BaseVyperException):
    """
    Base Vyper internal exception class.

    This exception is not raised directly, it is subclassed by other internal
    exceptions.

    Internal exceptions are raised as a means of telling the user that the
    compiler has panicked, and that filing a bug report would be appropriate.
    """

    def __str__(self):
        return (
            f"{super().__str__()}\n\n"
            "This is an unhandled internal compiler error. "
            "Please create an issue on Github to notify the developers!\n"
            "https://github.com/vyperlang/vyper/issues/new?template=bug.md"
        )


class CompilerPanic(VyperInternalException):
    """General unexpected error during compilation."""


class CodegenPanic(VyperInternalException):
    """Invalid code generated during codegen phase"""


class UnexpectedNodeType(VyperInternalException):
    """Unexpected AST node type."""


class UnexpectedValue(VyperInternalException):
    """Unexpected Value."""


class UnfoldableNode(VyperInternalException):
    """Constant folding logic cannot be applied to an AST node."""


class TypeCheckFailure(VyperInternalException):
    """An issue was not caught during type checking that should have been."""


class InvalidABIType(VyperInternalException):
    """An internal routine constructed an invalid ABI type"""


@contextlib.contextmanager
def tag_exceptions(node, fallback_exception_type=CompilerPanic, note=None):
    try:
        yield
    except _BaseVyperException as e:
        if not e.annotations and not e.lineno:
            tb = e.__traceback__
            raise e.with_annotation(node).with_traceback(tb) from None
        raise e from None
    except Exception as e:
        tb = e.__traceback__
        fallback_message = f"unhandled exception {e}"
        if note:
            fallback_message += f", {note}"
        raise fallback_exception_type(fallback_message, node).with_traceback(tb)

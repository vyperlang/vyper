# Attempts to display the line and column of violating code.
class ParserException(Exception):
    def __init__(self, message='Error Message not found.', item=None):
        self.message = message
        self.lineno = None
        self.col_offset = None

        if isinstance(item, tuple):  # is a position.
            self.lineno, self.col_offset = item
        elif item and hasattr(item, 'lineno'):
            self.set_err_pos(item.lineno, item.col_offset)
            if hasattr(item, 'source_code'):
                self.source_code = item.source_code.splitlines()

    def set_err_pos(self, lineno, col_offset):
        if not self.lineno:
            self.lineno = lineno

            if not self.col_offset:
                self.col_offset = col_offset

    def __str__(self):
        output = self.message

        if self.lineno and hasattr(self, 'source_code'):

            output = 'line %d: %s\n%s' % (
                self.lineno,
                output,
                self.source_code[self.lineno - 1]
            )

            if self.col_offset:
                col = '-' * self.col_offset + '^'
                output += '\n' + col

        elif self.lineno is not None and self.col_offset is not None:
            output = 'line %d:%d %s' % (
                self.lineno,
                self.col_offset,
                output
            )

        return output


class VariableDeclarationException(ParserException):
    pass


class StructureException(ParserException):
    pass


class ConstancyViolationException(ParserException):
    pass


class NonPayableViolationException(ParserException):
    pass


class InvalidLiteralException(ParserException):
    pass


class InvalidTypeException(ParserException):
    pass


class TypeMismatchException(ParserException):
    pass


class FunctionDeclarationException(ParserException):
    pass


class EventDeclarationException(ParserException):
    pass

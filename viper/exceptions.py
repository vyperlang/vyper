from contextlib import ContextDecorator


class CompilationContext(ContextDecorator):
    _code = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    @property
    def code(self):
        return self.__class__._code

    @code.setter
    def code(self, val):
        assert isinstance(val, list)
        self.__class__._code = val


# Attempts to display the line and column of violating code.
class ParserException(Exception):
    def __init__(self, message='Error Message not found.', item=None):
        self.message = message
        if item:
            self.set_err_pos(item.lineno, item.col_offset)

    def set_err_pos(self, lineno, col_offset):
        if not hasattr(self, 'lineno'):
            self.lineno = lineno
            if not hasattr(self, 'col_offset'):
                self.col_offset = col_offset

    def __str__(self):
        output = self.message
        with CompilationContext() as context:
            if hasattr(self, 'lineno'):
                output = 'line ' + str(self.lineno) + ': ' + output + '\n' + context.code[self.lineno-1]
                if hasattr(self, 'col_offset'):
                    col = ''.join(['-' for i in range(self.col_offset)]) + '^'
                    output = output + '\n' + col
        return output


class VariableDeclarationException(ParserException):
    pass


class StructureException(ParserException):
    pass


class ConstancyViolationException(ParserException):
    pass


class InvalidLiteralException(ParserException):
    pass


class InvalidTypeException(ParserException):
    pass


class TypeMismatchException(ParserException):
    pass

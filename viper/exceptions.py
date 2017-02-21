# Attempts to display the line and column of violating code.
class ParserException(Exception):
    def __init__(self, message='Error Message not found.', item=None):
        self.message = message
        if item:
            self.set_err_pos(item.lineno, item.col_offset)
            self.source_code = item.source_code.splitlines()

    def set_err_pos(self, lineno, col_offset):
        if not hasattr(self, 'lineno'):
            self.lineno = lineno
            if not hasattr(self, 'col_offset'):
                self.col_offset = col_offset

    def __str__(self):
        output = self.message
        if hasattr(self, 'lineno'):
            output = 'line ' + str(self.lineno) + ': ' + output + '\n' + self.source_code[self.lineno-1]
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

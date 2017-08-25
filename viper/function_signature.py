from .types import get_size_of_type, canonicalize_type, parse_type, \
    ByteArrayType
from .utils import fourbytes_to_int, sha3, is_varname_valid
import ast

from .exceptions import InvalidTypeException, TypeMismatchException, \
    VariableDeclarationException, StructureException, ConstancyViolationException, \
    InvalidTypeException, InvalidLiteralException, NonPayableViolationException

# Function argument
class VariableRecord():
    def __init__(self, name, pos, typ, mutable):
        self.name = name
        self.pos = pos
        self.typ = typ
        self.mutable = mutable

    @property
    def size(self):
        return get_size_of_type(self.typ)

# Function signature object
class FunctionSignature():
    def __init__(self, name, args, output_type, const, payable, internal, sig, method_id):
        self.name = name
        self.args = args
        self.output_type = output_type
        self.const = const
        self.payable = payable
        self.internal = internal
        self.sig = sig
        self.method_id = method_id
        self.gas = None

    # Get a signature from a function definition
    @classmethod
    def from_definition(cls, code):
        name = code.name
        pos = 0 
        # Determine the arguments, expects something of the form def foo(arg1: num, arg2: num ...
        args = []
        for arg in code.args.args:
            typ = arg.annotation
            if not isinstance(arg.arg, str):
                raise VariableDeclarationException("Argument name invalid", arg)
            if not typ:
                raise InvalidTypeException("Argument must have type", arg)
            if not is_varname_valid(arg.arg):
                raise VariableDeclarationException("Argument name invalid or reserved: "+arg.arg, arg)
            if arg.arg in (x.name for x in args):
                raise VariableDeclarationException("Duplicate function argument name: "+arg.arg, arg)
            parsed_type = parse_type(typ, None)
            args.append(VariableRecord(arg.arg, pos, parsed_type, False))
            if isinstance(parsed_type, ByteArrayType):
                pos += 32
            else:
                pos += get_size_of_type(parsed_type) * 32
        # Apply decorators
        const, payable, internal = False, False, False
        for dec in code.decorator_list:
            if isinstance(dec, ast.Name) and dec.id == "constant":
                const = True
            elif isinstance(dec, ast.Name) and dec.id == "payable":
                payable = True
            elif isinstance(dec, ast.Name) and dec.id == "internal":
                internal = True
            else:
                raise StructureException("Bad decorator", dec)
        # Determine the return type and whether or not it's constant. Expects something
        # of the form:
        # def foo(): ...
        # def foo() -> num: ... 
        # If there is no return type, ie. it's of the form def foo(): ...
        # and NOT def foo() -> type: ..., then it's null
        if not code.returns:
            output_type = None
        elif isinstance(code.returns, (ast.Name, ast.Compare, ast.Subscript, ast.Call)):
            output_type = parse_type(code.returns, None)
        else:
            raise InvalidTypeException("Output type invalid or unsupported: %r" % parse_type(code.returns, None), code.returns)
        # Output type must be canonicalizable
        if output_type is not None:
            assert canonicalize_type(output_type)
        # Get the canonical function signature
        sig = name + '(' + ','.join([canonicalize_type(parse_type(arg.annotation, None)) for arg in code.args.args]) + ')'
        # Take the first 4 bytes of the hash of the sig to get the method ID
        method_id = fourbytes_to_int(sha3(bytes(sig, 'utf-8'))[:4])
        return cls(name, args, output_type, const, payable, internal, sig, method_id)

    def to_abi_dict(self):
        return {
            "name": self.sig,
            "outputs": [{"type": canonicalize_type(self.output_type), "name": "out"}] if self.output_type else [],
            "inputs": [{"type": canonicalize_type(arg.typ), "name": arg.name} for arg in self.args],
            "constant": self.const,
            "payable": self.payable,
            "type": "constructor" if self.name == "__init__" else "function"
        }

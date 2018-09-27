import ast
from collections import Counter

from vyper.exceptions import (
    InvalidTypeException,
    StructureException,
    FunctionDeclarationException
)
from vyper.types import ByteArrayType
from vyper.types import (
    canonicalize_type,
    get_size_of_type,
    parse_type,
    TupleType
)
from vyper.utils import (
    fourbytes_to_int,
    is_varname_valid,
    sha3,
)
from vyper.parser.lll_node import LLLnode


# Function argument
class VariableRecord():
    def __init__(self, name, pos, typ, mutable, blockscopes=[]):
        self.name = name
        self.pos = pos
        self.typ = typ
        self.mutable = mutable
        self.blockscopes = blockscopes

    @property
    def size(self):
        return get_size_of_type(self.typ)


class ContractRecord(VariableRecord):
    def __init__(self, *args):
        super(ContractRecord, self).__init__(*args)


# Function signature object
class FunctionSignature():
    def __init__(self, name, args, output_type, const, payable, private, sig, method_id, custom_units):
        self.name = name
        self.args = args
        self.output_type = output_type
        self.const = const
        self.payable = payable
        self.private = private
        self.sig = sig
        self.method_id = method_id
        self.gas = None
        self.custom_units = custom_units

    # Get the canonical function signature
    @staticmethod
    def get_full_sig(func_name, args, sigs, custom_units):

        def get_type(arg):
            if isinstance(arg, LLLnode):
                return canonicalize_type(arg.typ)
            elif hasattr(arg, 'annotation'):
                return canonicalize_type(parse_type(arg.annotation, None, sigs, custom_units=custom_units))
        return func_name + '(' + ','.join([get_type(arg) for arg in args]) + ')'

    # Get a signature from a function definition
    @classmethod
    def from_definition(cls, code, sigs=None, custom_units=None, contract_def=False, constant=False):
        name = code.name
        pos = 0

        if not is_varname_valid(name, custom_units=custom_units):
            raise FunctionDeclarationException("Function name invalid: " + name)
        # Determine the arguments, expects something of the form def foo(arg1: int128, arg2: int128 ...
        args = []
        for arg in code.args.args:
            typ = arg.annotation
            if not typ:
                raise InvalidTypeException("Argument must have type", arg)
            if not is_varname_valid(arg.arg, custom_units=custom_units):
                raise FunctionDeclarationException("Argument name invalid or reserved: " + arg.arg, arg)
            if arg.arg in (x.name for x in args):
                raise FunctionDeclarationException("Duplicate function argument name: " + arg.arg, arg)
            parsed_type = parse_type(typ, None, sigs, custom_units=custom_units)
            args.append(VariableRecord(arg.arg, pos, parsed_type, False))
            if isinstance(parsed_type, ByteArrayType):
                pos += 32
            else:
                pos += get_size_of_type(parsed_type) * 32

        # Apply decorators
        const, payable, private, public = False, False, False, False
        for dec in code.decorator_list:
            if isinstance(dec, ast.Name) and dec.id == "constant":
                const = True
            elif isinstance(dec, ast.Name) and dec.id == "payable":
                payable = True
            elif isinstance(dec, ast.Name) and dec.id == "private":
                private = True
            elif isinstance(dec, ast.Name) and dec.id == "public":
                public = True
            else:
                raise StructureException("Bad decorator", dec)

        if public and private:
            raise StructureException("Cannot use public and private decorators on the same function: {}".format(name))
        if payable and const:
            raise StructureException("Function {} cannot be both constant and payable.".format(name))
        if payable and private:
            raise StructureException("Function {} cannot be both private and payable.".format(name))
        if (not public and not private) and not contract_def:
            raise StructureException("Function visibility must be declared (@public or @private)", code)
        if constant:
            const = True
        # Determine the return type and whether or not it's constant. Expects something
        # of the form:
        # def foo(): ...
        # def foo() -> int128: ...
        # If there is no return type, ie. it's of the form def foo(): ...
        # and NOT def foo() -> type: ..., then it's null
        if not code.returns:
            output_type = None
        elif isinstance(code.returns, (ast.Name, ast.Compare, ast.Subscript, ast.Call, ast.Tuple)):
            output_type = parse_type(code.returns, None, sigs, custom_units=custom_units)
        else:
            raise InvalidTypeException("Output type invalid or unsupported: %r" % parse_type(code.returns, None), code.returns, )
        # Output type must be canonicalizable
        if output_type is not None:
            assert isinstance(output_type, TupleType) or canonicalize_type(output_type)
        # Get the canonical function signature
        sig = cls.get_full_sig(name, code.args.args, sigs, custom_units)

        # Take the first 4 bytes of the hash of the sig to get the method ID
        method_id = fourbytes_to_int(sha3(bytes(sig, 'utf-8'))[:4])
        return cls(name, args, output_type, const, payable, private, sig, method_id, custom_units)

    def _generate_output_abi(self):
        t = self.output_type

        if not t:
            return []
        elif isinstance(t, TupleType):
            res = [canonicalize_type(x) for x in t.members]
        else:
            res = [canonicalize_type(t)]

        return [{"type": x, "name": "out"} for x in res]

    def to_abi_dict(self):
        return {
            "name": self.name,
            "outputs": self._generate_output_abi(),
            "inputs": [{"type": canonicalize_type(arg.typ), "name": arg.name} for arg in self.args],
            "constant": self.const,
            "payable": self.payable,
            "type": "constructor" if self.name == "__init__" else "function"
        }

    @classmethod
    def lookup_sig(cls, sigs, method_name, expr_args, stmt_or_expr, context):
        """ Using a list of args, determine the most accurate signature to use from the given context """

        def synonymise(s):
            return s.replace('int128', 'num').replace('uint256', 'num')
        # for sig in sigs['self']
        full_sig = cls.get_full_sig(stmt_or_expr.func.attr, expr_args, None, context.custom_units)
        method_names_dict = dict(Counter([x.split('(')[0] for x in context.sigs['self']]))
        if method_name not in method_names_dict:
            raise FunctionDeclarationException(
                "Function not declared yet (reminder: functions cannot "
                "call functions later in code than themselves): %s" % method_name
            )

        if method_names_dict[method_name] == 1:
            return next(sig for name, sig in context.sigs['self'].items() if name.split('(')[0] == method_name)
        if full_sig in context.sigs['self']:
            return context.sigs['self'][full_sig]
        else:
            synonym_sig = synonymise(full_sig)
            syn_sigs_test = [synonymise(k) for k in context.sigs.keys()]
            if len(syn_sigs_test) != len(set(syn_sigs_test)):
                raise Exception(
                    'Incompatible default parameter signature,'
                    'can not tell the number type of literal', stmt_or_expr
                )
            synonym_sigs = [(synonymise(k), v) for k, v in context.sigs['self'].items()]
            ssig = [s[1] for s in synonym_sigs if s[0] == synonym_sig]
            if len(ssig) == 0:
                raise FunctionDeclarationException(
                    "Function not declared yet (reminder: functions cannot "
                    "call functions later in code than themselves): %s" % method_name
                )
            return ssig[0]

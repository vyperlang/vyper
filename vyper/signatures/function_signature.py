from collections import (
    Counter,
)

from vyper import ast
from vyper.ast_utils import (
    to_python_ast,
)
from vyper.exceptions import (
    FunctionDeclarationException,
    InvalidTypeException,
    StructureException,
)
from vyper.parser.lll_node import (
    LLLnode,
)
from vyper.parser.parser_utils import (
    EnsureSingleExitChecker,
    UnmatchedReturnChecker,
    getpos,
)
from vyper.types import (
    ByteArrayLike,
    TupleLike,
    TupleType,
    canonicalize_type,
    delete_unit_if_empty,
    get_size_of_type,
    parse_type,
    print_unit,
    unit_from_type,
)
from vyper.utils import (
    check_valid_varname,
    fourbytes_to_int,
    function_whitelist,
    is_varname_valid,
    sha3,
)


# Function argument
class VariableRecord:
    def __init__(self, name, pos, typ, mutable, blockscopes=None, defined_at=None):
        self.name = name
        self.pos = pos
        self.typ = typ
        self.mutable = mutable
        self.blockscopes = [] if blockscopes is None else blockscopes
        self.defined_at = defined_at  # source code location variable record was defined.

    @property
    def size(self):
        return get_size_of_type(self.typ)


class ContractRecord(VariableRecord):
    def __init__(self, *args):
        super(ContractRecord, self).__init__(*args)


# Function signature object
class FunctionSignature:
    def __init__(self,
                 name,
                 args,
                 output_type,
                 const,
                 payable,
                 private,
                 nonreentrant_key,
                 sig,
                 method_id,
                 custom_units,
                 func_ast_code):
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
        self.nonreentrant_key = nonreentrant_key
        self.func_ast_code = func_ast_code
        self.calculate_arg_totals()

    def __str__(self):
        input_name = 'def ' + self.name + '(' + ','.join([str(arg.typ) for arg in self.args]) + ')'
        if self.output_type:
            return input_name + ' -> ' + str(self.output_type) + ':'
        return input_name + ':'

    def calculate_arg_totals(self):
        """ Calculate base arguments, and totals. """

        code = self.func_ast_code
        self.base_args = []
        self.total_default_args = 0

        if hasattr(code.args, 'defaults'):
            self.total_default_args = len(code.args.defaults)
            if self.total_default_args > 0:
                # all argument w/o defaults
                self.base_args = self.args[:-self.total_default_args]
            else:
                # No default args, so base_args = args.
                self.base_args = self.args
            # All default argument name/type definitions.
            self.default_args = code.args.args[-self.total_default_args:]
            # Keep all the value to assign to default parameters.
            self.default_values = dict(zip(
                [arg.arg for arg in self.default_args],
                code.args.defaults
            ))

        # Calculate the total sizes in memory the function arguments will take use.
        # Total memory size of all arguments (base + default together).
        self.max_copy_size = sum([
            32 if isinstance(arg.typ, ByteArrayLike) else get_size_of_type(arg.typ) * 32
            for arg in self.args
        ])
        # Total memory size of base arguments (arguments exclude default parameters).
        self.base_copy_size = sum([
            32 if isinstance(arg.typ, ByteArrayLike) else get_size_of_type(arg.typ) * 32
            for arg in self.base_args
        ])

    # Get the canonical function signature
    @staticmethod
    def get_full_sig(func_name, args, sigs, custom_units, custom_structs, constants):

        def get_type(arg):
            if isinstance(arg, LLLnode):
                return canonicalize_type(arg.typ)
            elif hasattr(arg, 'annotation'):
                return canonicalize_type(parse_type(
                    arg.annotation,
                    None,
                    sigs,
                    custom_units=custom_units,
                    custom_structs=custom_structs,
                    constants=constants,
                ))
        return func_name + '(' + ','.join([get_type(arg) for arg in args]) + ')'

    # Get a signature from a function definition
    @classmethod
    def from_definition(cls,
                        code,
                        sigs=None,
                        custom_units=None,
                        custom_structs=None,
                        contract_def=False,
                        constants=None,
                        constant=False):
        if not custom_structs:
            custom_structs = {}

        name = code.name
        mem_pos = 0

        valid_name, msg = is_varname_valid(name, custom_units, custom_structs, constants)
        if not valid_name and (not name.lower() in function_whitelist):
            raise FunctionDeclarationException("Function name invalid. " + msg, code)

        # Validate default values.
        for default_value in getattr(code.args, 'defaults', []):
            if not isinstance(default_value, (ast.Num, ast.Str, ast.Bytes, ast.List)):
                raise FunctionDeclarationException("Default parameter values have to be literals.")

        # Determine the arguments, expects something of the form def foo(arg1:
        # int128, arg2: int128 ...
        args = []
        for arg in code.args.args:
            # Each arg needs a type specified.
            typ = arg.annotation
            if not typ:
                raise InvalidTypeException("Argument must have type", arg)
            # Validate arg name.
            check_valid_varname(
                arg.arg,
                custom_units,
                custom_structs,
                constants,
                arg,
                "Argument name invalid or reserved. ",
                FunctionDeclarationException,
            )
            # Check for duplicate arg name.
            if arg.arg in (x.name for x in args):
                raise FunctionDeclarationException(
                    "Duplicate function argument name: " + arg.arg,
                    arg,
                )
            parsed_type = parse_type(
                typ,
                None,
                sigs,
                custom_units=custom_units,
                custom_structs=custom_structs,
                constants=constants,
            )
            args.append(VariableRecord(
                arg.arg,
                mem_pos,
                parsed_type,
                False,
                defined_at=getpos(arg),
            ))

            if isinstance(parsed_type, ByteArrayLike):
                mem_pos += 32
            else:
                mem_pos += get_size_of_type(parsed_type) * 32

        # Apply decorators
        const, payable, private, public, nonreentrant_key = False, False, False, False, ''
        for dec in code.decorator_list:
            if isinstance(dec, ast.Name) and dec.id == "constant":
                const = True
            elif isinstance(dec, ast.Name) and dec.id == "payable":
                payable = True
            elif isinstance(dec, ast.Name) and dec.id == "private":
                private = True
            elif isinstance(dec, ast.Name) and dec.id == "public":
                public = True
            elif isinstance(dec, ast.Call) and dec.func.id == "nonreentrant":
                if dec.args and len(dec.args) == 1 and isinstance(dec.args[0], ast.Str) and dec.args[0].s:  # noqa: E501
                    nonreentrant_key = dec.args[0].s
                else:
                    raise StructureException(
                        "@nonreentrant decorator requires a non-empty string to use as a key.",
                        dec
                    )
            else:
                raise StructureException("Bad decorator", dec)

        if public and private:
            raise StructureException(
                "Cannot use public and private decorators on the same function: {}".format(name)
            )
        if payable and const:
            raise StructureException(
                "Function {} cannot be both constant and payable.".format(name)
            )
        if payable and private:
            raise StructureException(
                "Function {} cannot be both private and payable.".format(name)
            )
        if (not public and not private) and not contract_def:
            raise StructureException(
                "Function visibility must be declared (@public or @private)",
                code,
            )
        if constant and nonreentrant_key:
            raise StructureException("@nonreentrant makes no sense on a @constant function.", code)
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
            output_type = parse_type(
                code.returns,
                None,
                sigs,
                custom_units=custom_units,
                custom_structs=custom_structs,
                constants=constants,
            )
        else:
            raise InvalidTypeException(
                "Output type invalid or unsupported: %r" % parse_type(code.returns, None),
                code.returns,
            )
        # Output type must be canonicalizable
        if output_type is not None:
            assert isinstance(output_type, TupleType) or canonicalize_type(output_type)
        # Get the canonical function signature
        sig = cls.get_full_sig(name, code.args.args, sigs, custom_units, custom_structs, constants)

        # Take the first 4 bytes of the hash of the sig to get the method ID
        method_id = fourbytes_to_int(sha3(bytes(sig, 'utf-8'))[:4])
        return cls(
            name,
            args,
            output_type,
            const,
            payable,
            private,
            nonreentrant_key,
            sig,
            method_id,
            custom_units,
            code
        )

    def _generate_output_abi(self, custom_units_descriptions=None):
        t = self.output_type
        if not t:
            return []
        elif isinstance(t, TupleType):
            res = [
                (canonicalize_type(x), print_unit(unit_from_type(x), custom_units_descriptions))
                for x in t.members
            ]
        elif isinstance(t, TupleLike):
            res = [
                (canonicalize_type(x), print_unit(unit_from_type(x), custom_units_descriptions))
                for x in t.tuple_members()
            ]
        else:
            res = [(canonicalize_type(t), print_unit(unit_from_type(t), custom_units_descriptions))]

        abi_outputs = [{"type": x, "name": "out", "unit": unit} for x, unit in res]

        for abi_output in abi_outputs:
            delete_unit_if_empty(abi_output)

        return abi_outputs

    def to_abi_dict(self, custom_units_descriptions=None):
        func_type = "function"
        if self.name == "__init__":
            func_type = "constructor"
        if self.name == "__default__":
            func_type = "fallback"

        abi_dict = {
            "name": self.name,
            "outputs": self._generate_output_abi(custom_units_descriptions),
            "inputs": [{
                "type": canonicalize_type(arg.typ),
                "name": arg.name,
                "unit": print_unit(unit_from_type(arg.typ), custom_units_descriptions)
            } for arg in self.args],
            "constant": self.const,
            "payable": self.payable,
            "type": func_type
        }

        for abi_input in abi_dict['inputs']:
            delete_unit_if_empty(abi_input)

        if self.name in ('__default__', '__init__'):
            del abi_dict['name']
        if self.name == '__default__':
            del abi_dict['inputs']
            del abi_dict['outputs']

        return abi_dict

    @classmethod
    def lookup_sig(cls, sigs, method_name, expr_args, stmt_or_expr, context):
        """
        Using a list of args, determine the most accurate signature to use from
        the given context
        """

        def synonymise(s):
            return s.replace('int128', 'num').replace('uint256', 'num')

        # for sig in sigs['self']
        full_sig = cls.get_full_sig(
            stmt_or_expr.func.attr,
            expr_args,
            None,
            context.custom_units,
            context.structs,
            context.constants,
        )
        method_names_dict = dict(Counter([x.split('(')[0] for x in context.sigs['self']]))
        if method_name not in method_names_dict:
            raise FunctionDeclarationException(
                "Function not declared yet (reminder: functions cannot "
                "call functions later in code than themselves): %s" % method_name
            )

        if method_names_dict[method_name] == 1:
            return next(
                sig
                for name, sig
                in context.sigs['self'].items()
                if name.split('(')[0] == method_name
            )
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

    def is_default_func(self):
        return self.name == '__default__'

    def is_initializer(self):
        return self.name == '__init__'

    def validate_return_statement_balance(self):
        # Run balanced return statement check.
        UnmatchedReturnChecker().visit(to_python_ast(self.func_ast_code))
        EnsureSingleExitChecker().visit(to_python_ast(self.func_ast_code))

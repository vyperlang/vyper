from collections import Counter

from vyper import ast as vy_ast
from vyper import parser
from vyper.exceptions import (
    FunctionDeclarationException,
    InvalidType,
    StructureException,
)
from vyper.parser.lll_node import LLLnode
from vyper.parser.parser_utils import (
    check_single_exit,
    check_unmatched_return,
    getpos,
)
from vyper.types import (
    ByteArrayLike,
    StructType,
    TupleLike,
    TupleType,
    canonicalize_type,
    get_size_of_type,
    parse_type,
)
from vyper.utils import (
    FUNCTION_WHITELIST,
    check_valid_varname,
    fourbytes_to_int,
    is_varname_valid,
    iterable_cast,
    keccak256,
)


# Function argument
class VariableRecord:
    def __init__(
        self, name, pos, typ, mutable, *, location="memory", blockscopes=None, defined_at=None
    ):
        self.name = name
        self.pos = pos
        self.typ = typ
        self.mutable = mutable
        self.location = location
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
    def __init__(
        self,
        name,
        args,
        output_type,
        mutability,
        internal,
        nonreentrant_key,
        sig,
        method_id,
        func_ast_code,
        is_from_json,
    ):
        self.name = name
        self.args = args
        self.output_type = output_type
        self.mutability = mutability
        self.internal = internal
        self.sig = sig
        self.method_id = method_id
        self.gas = None
        self.nonreentrant_key = nonreentrant_key
        self.func_ast_code = func_ast_code
        self.is_from_json = is_from_json
        self.calculate_arg_totals()

    def __str__(self):
        input_name = "def " + self.name + "(" + ",".join([str(arg.typ) for arg in self.args]) + ")"
        if self.output_type:
            return input_name + " -> " + str(self.output_type) + ":"
        return input_name + ":"

    def calculate_arg_totals(self):
        """ Calculate base arguments, and totals. """

        code = self.func_ast_code
        self.base_args = []
        self.total_default_args = 0

        if hasattr(code.args, "defaults"):
            self.total_default_args = len(code.args.defaults)
            if self.total_default_args > 0:
                # all argument w/o defaults
                self.base_args = self.args[: -self.total_default_args]
            else:
                # No default args, so base_args = args.
                self.base_args = self.args
            # All default argument name/type definitions.
            self.default_args = code.args.args[-self.total_default_args :]  # noqa: E203
            # Keep all the value to assign to default parameters.
            self.default_values = dict(
                zip([arg.arg for arg in self.default_args], code.args.defaults)
            )

        # Calculate the total sizes in memory the function arguments will take use.
        # Total memory size of all arguments (base + default together).
        self.max_copy_size = sum(
            [
                32 if isinstance(arg.typ, ByteArrayLike) else get_size_of_type(arg.typ) * 32
                for arg in self.args
            ]
        )
        # Total memory size of base arguments (arguments exclude default parameters).
        self.base_copy_size = sum(
            [
                32 if isinstance(arg.typ, ByteArrayLike) else get_size_of_type(arg.typ) * 32
                for arg in self.base_args
            ]
        )

    # Get the canonical function signature
    @staticmethod
    def get_full_sig(func_name, args, sigs, custom_structs):
        def get_type(arg):
            if isinstance(arg, LLLnode):
                return canonicalize_type(arg.typ)
            elif hasattr(arg, "annotation"):
                return canonicalize_type(
                    parse_type(arg.annotation, None, sigs, custom_structs=custom_structs,)
                )

        return func_name + "(" + ",".join([get_type(arg) for arg in args]) + ")"

    # Get a signature from a function definition
    @classmethod
    def from_definition(
        cls,
        code,
        sigs=None,
        custom_structs=None,
        interface_def=False,
        constant_override=False,
        is_from_json=False,
    ):
        if not custom_structs:
            custom_structs = {}

        name = code.name
        mem_pos = 0

        valid_name, msg = is_varname_valid(name, custom_structs)
        if not valid_name and (not name.lower() in FUNCTION_WHITELIST):
            raise FunctionDeclarationException("Function name invalid. " + msg, code)

        # Validate default values.
        for default_value in getattr(code.args, "defaults", []):
            validate_default_values(default_value)

        # Determine the arguments, expects something of the form def foo(arg1:
        # int128, arg2: int128 ...
        args = []
        for arg in code.args.args:
            # Each arg needs a type specified.
            typ = arg.annotation
            if not typ:
                raise InvalidType("Argument must have type", arg)
            # Validate arg name.
            check_valid_varname(
                arg.arg,
                custom_structs,
                arg,
                "Argument name invalid or reserved. ",
                FunctionDeclarationException,
            )
            # Check for duplicate arg name.
            if arg.arg in (x.name for x in args):
                raise FunctionDeclarationException(
                    "Duplicate function argument name: " + arg.arg, arg,
                )
            parsed_type = parse_type(typ, None, sigs, custom_structs=custom_structs,)
            args.append(
                VariableRecord(arg.arg, mem_pos, parsed_type, False, defined_at=getpos(arg),)
            )

            if isinstance(parsed_type, ByteArrayLike):
                mem_pos += 32
            else:
                mem_pos += get_size_of_type(parsed_type) * 32

        mutability = "nonpayable"  # Assume nonpayable by default
        internal = False
        external = False
        nonreentrant_key = ""

        # Update function properties from decorators
        # NOTE: Can't import enums here because of circular import
        for dec in code.decorator_list:
            if isinstance(dec, vy_ast.Name) and dec.id in ("payable", "view", "pure"):
                mutability = dec.id
            elif isinstance(dec, vy_ast.Name) and dec.id == "internal":
                internal = True
            elif isinstance(dec, vy_ast.Name) and dec.id == "external":
                external = True
            elif isinstance(dec, vy_ast.Call) and dec.func.id == "nonreentrant":
                if nonreentrant_key:
                    raise StructureException(
                        "Only one @nonreentrant decorator allowed per function", dec
                    )
                if (
                    dec.args
                    and len(dec.args) == 1
                    and isinstance(dec.args[0], vy_ast.Str)
                    and dec.args[0].s
                ):  # noqa: E501
                    nonreentrant_key = dec.args[0].s
                else:
                    raise StructureException(
                        "@nonreentrant decorator requires a non-empty string to use as a key.", dec
                    )
            else:
                raise StructureException("Bad decorator", dec)

        if constant_override:
            # In case this override is abused, match previous behavior
            if mutability == "payable":
                raise StructureException(f"Function {name} cannot be both constant and payable.")
            mutability = "view"

        if external and internal:
            raise StructureException(
                f"Cannot use external and internal decorators on the same function: {name}"
            )
        if mutability == "payable" and internal:
            raise StructureException(f"Function {name} cannot be both internal and payable.")
        if (not external and not internal) and not interface_def:
            raise StructureException(
                "Function visibility must be declared (@external or @internal)", code,
            )
        if mutability in ("view", "pure") and nonreentrant_key:
            raise StructureException(
                f"@nonreentrant makes no sense on a @{mutability} function.", code
            )

        # Determine the return type and whether or not it's constant. Expects something
        # of the form:
        # def foo(): ...
        # def foo() -> int128: ...
        # If there is no return type, ie. it's of the form def foo(): ...
        # and NOT def foo() -> type: ..., then it's null
        if not code.returns:
            output_type = None
        elif isinstance(
            code.returns, (vy_ast.Name, vy_ast.Compare, vy_ast.Subscript, vy_ast.Call, vy_ast.Tuple)
        ):
            output_type = parse_type(code.returns, None, sigs, custom_structs=custom_structs,)
        else:
            raise InvalidType(
                f"Output type invalid or unsupported: {parse_type(code.returns, None)}",
                code.returns,
            )
        # Output type must be canonicalizable
        if output_type is not None:
            assert isinstance(output_type, TupleType) or canonicalize_type(output_type)
        # Get the canonical function signature
        sig = cls.get_full_sig(name, code.args.args, sigs, custom_structs)

        # Take the first 4 bytes of the hash of the sig to get the method ID
        method_id = fourbytes_to_int(keccak256(bytes(sig, "utf-8"))[:4])
        return cls(
            name,
            args,
            output_type,
            mutability,
            internal,
            nonreentrant_key,
            sig,
            method_id,
            code,
            is_from_json,
        )

    @iterable_cast(dict)
    def _generate_base_type(self, arg_type, name=""):
        yield "type", canonicalize_type(arg_type)
        yield "name", name

    def _generate_param_abi(self, out_arg, name=""):
        if isinstance(out_arg, TupleLike):
            return {
                "type": "tuple",
                "name": name,
                "components": [
                    self._generate_param_abi(
                        member_type, name=n if type(out_arg) is StructType else "",
                    )
                    for n, member_type in out_arg.tuple_items()
                ],
            }
        return self._generate_base_type(arg_type=out_arg, name=name)

    def _generate_outputs_abi(self):
        if not self.output_type:
            return []
        elif isinstance(self.output_type, StructType):
            # Flatten structs at the base level of output
            # NOTE: structs inside of structs still encode as tuples
            return [
                self._generate_param_abi(typ, name) for name, typ in self.output_type.tuple_items()
            ]
        elif isinstance(self.output_type, TupleType):
            # Flatten tuples at the base level of output
            return [self._generate_param_abi(x,) for x in self.output_type.members]
        else:
            return [self._generate_param_abi(self.output_type)]

    def _generate_inputs_abi(self):
        if not self.args:
            return []
        else:
            return [self._generate_param_abi(x.typ, name=x.name) for x in self.args]

    def to_abi_dict(self):
        func_type = "function"
        if self.name == "__init__":
            func_type = "constructor"
        if self.name == "__default__":
            func_type = "fallback"

        abi_dict = {
            "name": self.name,
            "outputs": self._generate_outputs_abi(),
            "inputs": self._generate_inputs_abi(),
            "stateMutability": self.mutability,
            "type": func_type,
        }

        if self.name in ("__default__", "__init__"):
            del abi_dict["name"]
        if self.name == "__default__":
            del abi_dict["inputs"]
            del abi_dict["outputs"]

        return abi_dict

    @classmethod
    def lookup_sig(cls, sigs, method_name, expr_args, stmt_or_expr, context):
        """
        Using a list of args, determine the most accurate signature to use from
        the given context
        """

        def synonymise(s):
            return s.replace("int128", "num").replace("uint256", "num")

        # for sig in sigs['self']
        full_sig = cls.get_full_sig(stmt_or_expr.func.attr, expr_args, None, context.structs,)
        method_names_dict = dict(Counter([x.split("(")[0] for x in context.sigs["self"]]))
        if method_name not in method_names_dict:
            raise FunctionDeclarationException(
                "Function not declared yet (reminder: functions cannot "
                f"call functions later in code than themselves): {method_name}"
            )

        if method_names_dict[method_name] == 1:
            return next(
                sig
                for name, sig in context.sigs["self"].items()
                if name.split("(")[0] == method_name
            )
        if full_sig in context.sigs["self"]:
            return context.sigs["self"][full_sig]
        else:
            synonym_sig = synonymise(full_sig)
            syn_sigs_test = [synonymise(k) for k in context.sigs.keys()]
            if len(syn_sigs_test) != len(set(syn_sigs_test)):
                raise Exception(
                    "Incompatible default parameter signature,"
                    "can not tell the number type of literal",
                    stmt_or_expr,
                )
            synonym_sigs = [(synonymise(k), v) for k, v in context.sigs["self"].items()]
            ssig = [s[1] for s in synonym_sigs if s[0] == synonym_sig]
            if len(ssig) == 0:
                raise FunctionDeclarationException(
                    "Function not declared yet (reminder: functions cannot "
                    f"call functions later in code than themselves): {method_name}"
                )
            return ssig[0]

    def is_default_func(self):
        return self.name == "__default__"

    def is_initializer(self):
        return self.name == "__init__"

    def validate_return_statement_balance(self):
        # Run balanced return statement check.
        check_unmatched_return(self.func_ast_code)
        check_single_exit(self.func_ast_code)


def validate_default_values(node):
    if isinstance(node, vy_ast.Name) and node.id in parser.expr.BUILTIN_CONSTANTS:
        return
    if isinstance(node, vy_ast.Attribute) and node.value.id in parser.expr.ENVIRONMENT_VARIABLES:
        return
    if not isinstance(node, (vy_ast.Constant, vy_ast.List)):
        raise FunctionDeclarationException(
            "Default value must be a literal, built-in constant, or environment variable.", node
        )
    if isinstance(node, vy_ast.List):
        for n in node.elements:
            validate_default_values(n)

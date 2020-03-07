from collections import (
    OrderedDict,
)

from vyper import (
    ast as vy_ast,
)
from vyper.context import (
    namespace,
)
from vyper.context.definitions.bases import (
    BaseDefinition,
    FunctionDefinition,
)
from vyper.context.definitions.utils import (
    get_value_from_node,
)
from vyper.context.definitions.variable import (
    Variable,
)
from vyper.context.types import (
    compare_types,
    get_builtin_type,
    get_type_from_annotation,
    get_type_from_node,
)
from vyper.context.types.bases import (
    UnionType,
)
from vyper.context.utils import (
    validate_call_args,
)
from vyper.exceptions import (
    InvalidLiteral,
    InvalidType,
    TypeMismatch,
)

# Eventually this logic will move to vyper/functions and be refactored into
# several modules. Until work begins integrating vyper/context into the rest
# of the vyper package, it is difficult to envision the final implementation
# for these classes. So they temporarily live here.  @iamdefinitelyahuman


class BuiltinFunctionDefinition(BaseDefinition):

    def __init__(self):
        super().__init__(self._id)


class SimpleBuiltinDefinition(FunctionDefinition, BuiltinFunctionDefinition):
    """
    Base class for builtin functions where the inputs and return types are fixed.

    Builtins must define a `get_call_return_type` method that accepts an ast Call node and
    optionally returns a Variable object.

    Class attributes
    ----------------
    _id : str
        Name of the builtin function.
    _inputs : list
        A list of two item tuples as (name, type), corresponding to each positional
        argument for the function.
    _arg_count : tuple, optional
        A two item tuple of the minimum and maximum number of allowable positional
        arguments when calling this method. Used to make some arguments optional.
        If not included, every argument specified in _inputs is required.
    _return_type : str | list
        A string or list of strings defining the return type for the function. May
        also be None if the function does not return a value.
    """
    def __init__(self):
        arguments = OrderedDict()
        for name, types in self._inputs:
            type_ = get_builtin_type(types)
            if isinstance(type_, UnionType):
                type_.lock()
            arguments[name] = type_
        return_type = get_builtin_type(self._return_type) if self._return_type else None
        arg_count = getattr(self, '_arg_count', len(arguments))
        FunctionDefinition.__init__(self, self._id, arguments, arg_count, return_type)


class Floor(SimpleBuiltinDefinition):

    _id = "floor"
    _inputs = [("value", "decimal")]
    _return_type = "int128"


class Ceil(SimpleBuiltinDefinition):

    _id = "ceil"
    _inputs = [("value", "decimal")]
    _return_type = "int128"


class Len(SimpleBuiltinDefinition):

    _id = "len"
    _inputs = [("b", {"bytes", "string"})]
    _return_type = "int128"


class AddMod(SimpleBuiltinDefinition):

    _id = "uint256_addmod"
    _inputs = [("a", "uint256"), ("b", "uint256"), ("c", "uint256")]
    _return_type = "uint256"


class MulMod(SimpleBuiltinDefinition):

    _id = "uint256_mulmod"
    _inputs = [("a", "uint256"), ("b", "uint256"), ("c", "uint256")]
    _return_type = "uint256"


class Sqrt(SimpleBuiltinDefinition):

    _id = "sqrt"
    _inputs = [("d", "decimal")]
    _return_type = "decimal"


class ECRecover(SimpleBuiltinDefinition):

    _id = "ecrecover"
    _inputs = [("hash", "bytes32"), ("v", "uint256"), ("r", "uint256"), ("s", "uint256")]
    _return_type = "address"


class ECAdd(SimpleBuiltinDefinition):

    _id = "ecadd"
    _inputs = [("a", ["uint256", "uint256"]), ("b", ["uint256", "uint256"])]
    _return_type = ["uint256", "uint256"]


class ECMul(SimpleBuiltinDefinition):

    _id = "ecmul"
    _inputs = [("point", ["uint256", "uint256"]), ("scalar", "uint256")]
    _return_type = ["uint256", "uint256"]


class Send(SimpleBuiltinDefinition):

    _id = "send"
    _inputs = [("to", "address"), ("value", ("uint256", "wei"))]
    _return_type = None


class SelfDestruct(SimpleBuiltinDefinition):

    _id = "selfdestruct"
    _inputs = [("to", "address")]
    _return_type = None


class AssertModifiable(SimpleBuiltinDefinition):

    _id = "assert_modifiable"
    _inputs = [("cond", "bool")]
    _return_type = None


class CreateForwarder(SimpleBuiltinDefinition):

    _id = "create_forwarder_to"
    _inputs = [("target", "address"), ("value", ("uint256", "wei"))]
    _arg_count = (1, 2)
    _return_type = "address"


class Blockhash(SimpleBuiltinDefinition):

    _id = "blockhash"
    _inputs = [("block_num", "uint256")]
    _return_type = "bytes32"


class Keccak256(SimpleBuiltinDefinition):

    _id = "keccak256"
    _inputs = [("value", {"string", "bytes", "bytes32"})]
    _return_type = "bytes32"


class Sha256(SimpleBuiltinDefinition):

    _id = "sha256"
    _inputs = [("value", {"string", "bytes", "bytes32"})]
    _return_type = "bytes32"


class BitwiseAnd(SimpleBuiltinDefinition):

    _id = "bitwise_and"
    _inputs = [("x", "uint256"), ("y", "uint256")]
    _return_type = "uint256"


class BitwiseNot(SimpleBuiltinDefinition):

    _id = "bitwise_not"
    _inputs = [("x", "uint256"), ("y", "uint256")]
    _return_type = "uint256"


class BitwiseOr(SimpleBuiltinDefinition):

    _id = "bitwise_or"
    _inputs = [("x", "uint256"), ("y", "uint256")]
    _return_type = "uint256"


class BitwiseXor(SimpleBuiltinDefinition):

    _id = "bitwise_xor"
    _inputs = [("x", "uint256"), ("y", "uint256")]
    _return_type = "uint256"


class Shift(SimpleBuiltinDefinition):

    _id = "shift"
    _inputs = [("x", "uint256"), ("_shift", "int128")]
    _return_type = "uint256"


class AsWeiValue(SimpleBuiltinDefinition):

    _id = "as_wei_value"
    _inputs = [("value", "uint256"), ("unit", "string")]
    _return_type = ("uint256", "wei")

    wei_denoms = {
        ("wei", ): 1,
        ("femtoether", "kwei", "babbage"): 10**3,
        ("picoether", "mwei", "lovelace"): 10**6,
        ("nanoether", "gwei", "shannon"): 10**9,
        ("microether", "szabo", ): 10**12,
        ("milliether", "finney", ): 10**15,
        ("ether", ): 10**18,
        ("kether", "grand"): 10**21,
    }

    def get_call_return_type(self, node: vy_ast.Call):
        validate_call_args(node, 2)
        if not isinstance(node.args[1], vy_ast.Str):
            # TODO standard way to indicate a value must be a literal?
            raise InvalidType(
                "Wei denomination must be given as a literal string", node.args[1]
            )
        denom = next((v for k, v in self.wei_denoms.items() if node.args[1].value in k), False)
        if not denom:
            raise InvalidLiteral(
                f"Invalid denomination '{node.args[1].value}', valid denominations are: "
                f"{', '.join(x[0] for x in self.wei_denoms)}",
                node.args[1]
            )
        return super().get_call_return_type(node)


class Slice(SimpleBuiltinDefinition):

    _id = "slice"
    _inputs = [("b", {'bytes', 'bytes32', 'string'}), ('start', 'int128'), ('length', 'int128')]
    _return_type = None

    def get_call_return_type(self, node: vy_ast.Call):
        super().get_call_return_type(node)

        start, length = (get_value_from_node(i) for i in node.args[1:])
        if not isinstance(start, int) or start < 0:
            raise InvalidLiteral("Start must be a positive literal integer ", node.args[1])
        if not isinstance(length, int) or length < 1:
            raise InvalidLiteral(
                "Length must be a literal integer greater than zero", node.args[2]
            )

        input_type = get_type_from_node(node.args[0])
        return_length = length - start
        if getattr(input_type, 'is_bytes', None):
            return get_builtin_type(("bytes", return_length))
        else:
            return get_builtin_type(("string", return_length))


class RawCall(SimpleBuiltinDefinition):

    _id = "raw_call"
    _inputs = [
        ("to", "address"),
        ("data", "bytes"),
        ("outsize", {"int128", "uint256"}),
        ("gas", "uint256"),
        ("value", ("uint256", "wei")),
        ("is_delegate_call", "bool")
    ]
    _arg_count = (4, 6)
    _return_type = "bytes"

    def get_call_return_type(self, node: vy_ast.Call):
        return_type = super().get_call_return_type(node)
        min_length = get_value_from_node(node.args[2])
        if isinstance(min_length, Variable):
            min_length = min_length.literal_value()
        return_type.min_length = min_length
        return return_type


class Min(BuiltinFunctionDefinition):

    _id = "min"

    def get_call_return_type(self, node: vy_ast.Call):
        validate_call_args(node, 2)
        left, right = (get_type_from_node(i) for i in node.args)
        if not hasattr(left, 'is_numeric'):
            raise InvalidType("Can only calculate min on numeric types", node)
        compare_types(left, right, node)
        return left


class Max(BuiltinFunctionDefinition):

    _id = "max"

    def get_call_return_type(self, node: vy_ast.Call):
        validate_call_args(node, 2)
        left, right = (get_type_from_node(i) for i in node.args)
        if not hasattr(left, 'is_numeric'):
            raise InvalidType("Can only calculate max on numeric types", node)
        compare_types(left, right, node)
        return left


class Clear(BuiltinFunctionDefinition):

    _id = "clear"

    def get_call_return_type(self, node: vy_ast.Call):
        validate_call_args(node, 1)
        get_type_from_node(node.args[0])
        return None


class AsUnitlessNumber(BuiltinFunctionDefinition):

    _id = "as_unitless_number"

    def get_call_return_type(self, node: vy_ast.Call):
        validate_call_args(node, 1)
        value = get_value_from_node(node.args[0])
        if not getattr(getattr(value, 'type', None), 'is_value_type', None):
            raise InvalidType("Not a value type", node.args[0])
        if not hasattr(value.type, 'unit'):
            raise InvalidType(f"Type '{value.type}' has no unit", node.args[0])
        return_type = type(value.type)()
        del return_type.unit
        return return_type


class Concat(BuiltinFunctionDefinition):

    _id = "concat"

    def get_call_return_type(self, node: vy_ast.Call):
        validate_call_args(node, (2, float('inf')))
        type_list = [get_type_from_node(i) for i in node.args]

        idx = next((i for i in type_list if not getattr(i, 'is_bytes', None)), None)
        if idx is not None:
            node = node.args[type_list.index(idx)]
            raise InvalidType("Concat values must be bytes", node)

        length = sum(i.min_length for i in type_list)
        return_type = get_builtin_type(("bytes", length))
        return return_type


class MethodID(BuiltinFunctionDefinition):

    _id = "method_id"

    def get_call_return_type(self, node: vy_ast.Call):
        validate_call_args(node, 2)
        if not isinstance(node.args[0], vy_ast.Str):
            raise InvalidType("method id must be given as a literal string", node.args[0])
        return_type = get_type_from_annotation(node.args[1])
        if not getattr(return_type, 'is_bytes', None) or return_type.length not in (4, 32):
            raise InvalidType("return type must be bytes32 or bytes[4]", node.args[1])
        return return_type


class Extract32(BuiltinFunctionDefinition):

    _id = "extract32"

    def get_call_return_type(self, node: vy_ast.Call):
        validate_call_args(node, (2, 3))
        target, length = (get_type_from_node(i) for i in node.args[:2])

        compare_types(target, namespace['bytes'], node.args[0])
        compare_types(length, namespace['int128'], node.args[1])

        # TODO union type, default types, any type?
        if len(node.args) == 3:
            return_type = get_type_from_annotation(node.args[2])
            if return_type._id not in ("bytes32", "int128", "address"):
                raise InvalidType("Invalid return type", node.args[2])

        else:
            return_type = get_builtin_type("bytes32")

        return return_type


class RawLog(BuiltinFunctionDefinition):

    _id = "raw_log"

    def get_call_return_type(self, node: vy_ast.Call):
        validate_call_args(node, 2)
        if not isinstance(node.args[0], vy_ast.List) or len(node.args[0].elts) > 4:
            raise InvalidType(
                "Expecting a list of 0-4 topics as first argument", node.args[0].elts[4]
            )
        if node.args[0].elts:
            log_type = get_type_from_node(node.args[0])
            compare_types(log_type[0], namespace['bytes32'], node.args[0])
        compare_types(get_type_from_node(node.args[1]), namespace['bytes'], node.args[1])
        return None


class Convert(BuiltinFunctionDefinition):

    # TODO this is just a wireframe, expand it with complete functionality
    # https://github.com/vyperlang/vyper/issues/1093

    _id = "convert"

    def get_call_return_type(self, node: vy_ast.Call):
        validate_call_args(node, 2)
        initial_type = get_type_from_node(node.args[0])
        if not getattr(initial_type, 'is_value_type', None):
            raise InvalidType(f"Cannot convert type '{initial_type}'", node.args[0])
        target_type = get_builtin_type(node.args[1].id)
        try:
            compare_types(initial_type, target_type, node)
        except TypeMismatch:
            pass
        else:
            raise InvalidType(f"Value and target type are both '{target_type}'", node)

        try:
            validation_fn = getattr(self, f"validate_to_{target_type._id}")
        except AttributeError:
            raise InvalidType(
                f"Unsupported destination type '{target_type}'", node.args[1]
            )

        validation_fn(initial_type)
        return target_type

    def validate_to_bool(self, initial_type):
        pass

    def validate_to_decimal(self, initial_type):
        pass

    def validate_to_int128(self, initial_type):
        pass

    def validate_to_uint256(self, initial_type):
        pass

    def validate_to_bytes32(self, initial_type):
        pass

from collections import (
    OrderedDict,
)
from decimal import (
    Decimal,
)
import math
from typing import (
    Optional,
    Type,
    Union,
)

from vyper import (
    ast as vy_ast,
)
from vyper.context import (
    namespace,
)
from vyper.context.definitions.bases import (
    BaseDefinition,
    CallableDefinition,
)
from vyper.context.definitions.utils import (
    get_definition_from_node,
    get_literal_or_raise,
    get_type_from_annotation,
)
from vyper.context.definitions.values import (
    Literal,
    Reference,
)
from vyper.context.types import (
    UnionType,
    get_builtin_type,
)
from vyper.context.types.bases import (
    ValueType,
)
from vyper.context.types.core import (
    BytesBase,
    NumericBase,
    StringBase,
)
from vyper.context.utils import (
    compare_types,
    is_subtype,
    validate_call_args,
)
from vyper.exceptions import (
    CompilerPanic,
    InvalidLiteral,
    InvalidType,
    TypeMismatch,
    ZeroDivisionException,
)
from vyper.utils import (
    fourbytes_to_int,
    keccak256,
)

# Eventually this logic will move to vyper/functions and be refactored into
# several modules. Until work begins integrating vyper/context into the rest
# of the vyper package, it is difficult to envision the final implementation
# for these classes. So they temporarily live here.  @iamdefinitelyahuman


def _get_arg_values(node):
    return (get_literal_or_raise(i).value for i in node.args)


class BuiltinFunctionDefinition(BaseDefinition):

    def __init__(self):
        super().__init__(self._id)

    def evaluate(self, node):
        raise InvalidType(f"{self._id} cannot be folded", node)


class SimpleBuiltinDefinition(CallableDefinition, BuiltinFunctionDefinition):
    """
    Base class for builtin functions where the inputs and return types are fixed.

    Builtins must define a `fetch_call_return` method that accepts an ast Call node and
    optionally returns a `Reference` object.

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

        return_type = None
        if self._return_type:
            return_type = get_builtin_type(self._return_type)

        arg_count = getattr(self, '_arg_count', len(arguments))
        CallableDefinition.__init__(self, self._id, arguments, arg_count, return_type)


class Floor(SimpleBuiltinDefinition):

    _id = "floor"
    _inputs = [("value", "decimal")]
    _return_type = "int128"

    def evaluate(self, node: vy_ast.Call) -> vy_ast.Int:
        self.fetch_call_return(node)
        value, = _get_arg_values(node)
        return vy_ast.Int.from_node(node, value=math.floor(value))


class Ceil(SimpleBuiltinDefinition):

    _id = "ceil"
    _inputs = [("value", "decimal")]
    _return_type = "int128"

    def evaluate(self, node: vy_ast.Call) -> vy_ast.Int:
        self.fetch_call_return(node)
        value, = _get_arg_values(node)
        return vy_ast.Int.from_node(node, value=math.ceil(value))


class Len(SimpleBuiltinDefinition):

    _id = "len"
    _inputs = [("b", {"bytes", "string"})]
    _return_type = "int128"

    def evaluate(self, node: vy_ast.Call) -> vy_ast.Int:
        self.fetch_call_return(node)
        value, = _get_arg_values(node)
        return vy_ast.Int.from_node(node, value=len(value))


class AddMod(SimpleBuiltinDefinition):

    _id = "uint256_addmod"
    _inputs = [("a", "uint256"), ("b", "uint256"), ("c", "uint256")]
    _return_type = "uint256"

    def evaluate(self, node: vy_ast.Call) -> vy_ast.Int:
        self.fetch_call_return(node)
        a, b, c = _get_arg_values(node)
        value = (a + b) % c
        return vy_ast.Int.from_node(node, value=value)

    def fetch_call_return(self, node):
        return_value = super().fetch_call_return(node)
        if isinstance(node.args[2], vy_ast.Num) and node.args[2].value == 0:
            raise ZeroDivisionException("Modulo by 0", node.args[2])
        return return_value


class MulMod(SimpleBuiltinDefinition):

    _id = "uint256_mulmod"
    _inputs = [("a", "uint256"), ("b", "uint256"), ("c", "uint256")]
    _return_type = "uint256"

    def evaluate(self, node: vy_ast.Call) -> vy_ast.Int:
        self.fetch_call_return(node)
        a, b, c = _get_arg_values(node)
        value = (a * b) % c
        return vy_ast.Int.from_node(node, value=value)

    def fetch_call_return(self, node):
        return_value = super().fetch_call_return(node)
        if isinstance(node.args[2], vy_ast.Num) and node.args[2].value == 0:
            raise ZeroDivisionException("Modulo by 0", node.args[2])
        return return_value


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
    _inputs = [("to", "address"), ("value", "uint256")]
    _return_type = None


class SelfDestruct(SimpleBuiltinDefinition):

    _id = "selfdestruct"
    _inputs = [("to", "address")]
    _return_type = None
    _is_terminus = True


class AssertModifiable(SimpleBuiltinDefinition):

    _id = "assert_modifiable"
    _inputs = [("cond", "bool")]
    _return_type = None


class CreateForwarder(SimpleBuiltinDefinition):

    _id = "create_forwarder_to"
    _inputs = [("target", "address"), ("value", "uint256")]
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
    _inputs = [("x", "uint256")]
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
    _inputs = [("value", {"uint256", "int128", "decimal"}), ("unit", "string")]
    _return_type = "uint256"

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

    def evaluate(self, node: vy_ast.Call) -> vy_ast.Int:
        self.fetch_call_return(node)
        value, denom = _get_arg_values(node)
        denom = next(v for k, v in self.wei_denoms.items() if denom in k)
        return vy_ast.Int.from_node(node, value=int(value * denom))

    def fetch_call_return(self, node: vy_ast.Call) -> Reference:
        super().fetch_call_return(node)

        value = get_definition_from_node(node.args[0])
        if isinstance(value, Literal) and value.value < 0:
            raise InvalidLiteral("Negative wei value not allowed", node.args[0])

        denom_def = get_definition_from_node(node.args[1])
        if not isinstance(denom_def, Literal):
            raise InvalidType(
                "Wei denomination must be given as a literal string", node.args[1]
            )
        denom = next((v for k, v in self.wei_denoms.items() if denom_def.value in k), False)
        if not denom:
            raise InvalidLiteral(
                f"Invalid denomination '{denom_def.value}', valid denominations are: "
                f"{', '.join(x[0] for x in self.wei_denoms)}",
                node.args[1]
            )
        return Reference.from_type(self.return_type, "return value")


class Slice(SimpleBuiltinDefinition):

    _id = "slice"
    _inputs = [("b", {'bytes', 'bytes32', 'string'}), ('start', 'int128'), ('length', 'int128')]
    _return_type = None

    def fetch_call_return(self, node: vy_ast.Call) -> Reference:
        super().fetch_call_return(node)

        start, length = (get_definition_from_node(i) for i in node.args[1:])
        if isinstance(start, Literal) and start.value < 0:
            raise InvalidLiteral("Start must be a positive integer", node.args[1])
        if isinstance(length, Literal) and length.value < 1:
            raise InvalidLiteral("Length cannot be less than 1", node.args[2])

        input_var = get_definition_from_node(node.args[0])
        if is_subtype(input_var.type, BytesBase):
            type_ = get_builtin_type("bytes")
        else:
            type_ = get_builtin_type("string")
        if isinstance(length, Literal):
            type_.set_length(length.value)
        else:
            type_.set_min_length(input_var.type.length)
        return Reference.from_type(type_, "return value")


class RawCall(SimpleBuiltinDefinition):

    _id = "raw_call"
    _inputs = [
        ("to", "address"),
        ("data", "bytes"),
        ("outsize", {"int128", "uint256"}),
        ("gas", "uint256"),
        ("value", "uint256"),
        ("is_delegate_call", "bool")
    ]
    _arg_count = (2, 6)
    _return_type = None

    def fetch_call_return(self, node: vy_ast.Call) -> Optional[Reference]:
        super().fetch_call_return(node)
        if len(node.args) > 2:
            min_length = get_literal_or_raise(node.args[2]).value
        else:
            n = next((i.value for i in node.keywords if i.arg == "outsize"), False)
            if not n:
                return None
            min_length = get_literal_or_raise(n).value

        return_type = get_builtin_type('bytes')
        return_type.set_min_length(min_length)

        return Reference.from_type(return_type, "return value")


class Min(BuiltinFunctionDefinition):

    _id = "min"

    def evaluate(self, node):
        self.fetch_call_return(node)
        left, right = _get_arg_values(node)
        if isinstance(left, int):
            node_type = vy_ast.Int
        elif isinstance(left, Decimal):
            node_type = vy_ast.Decimal
        else:
            raise CompilerPanic(f"Unexpected value type: {type(left)}")
        return node_type.from_node(node, value=min(left, right))

    def fetch_call_return(self, node: vy_ast.Call) -> Reference:
        validate_call_args(node, 2)
        left, right = (get_definition_from_node(i).type for i in node.args)
        if not is_subtype(left, NumericBase):
            raise InvalidType("Can only calculate min on numeric types", node)
        compare_types(left, right, node)

        return Reference.from_type(left, "return value")


class Max(BuiltinFunctionDefinition):

    _id = "max"

    def evaluate(self, node: vy_ast.Call) -> Union[vy_ast.Int, vy_ast.Decimal]:
        self.fetch_call_return(node)
        left, right = _get_arg_values(node)
        node_type: Type[vy_ast.Num]
        if isinstance(left, int):
            node_type = vy_ast.Int
        elif isinstance(left, Decimal):
            node_type = vy_ast.Decimal
        else:
            raise CompilerPanic(f"Unexpected value type: {type(left)}")
        return node_type.from_node(node, value=max(left, right))

    def fetch_call_return(self, node: vy_ast.Call) -> Reference:
        validate_call_args(node, 2)
        left, right = (get_definition_from_node(i).type for i in node.args)
        if not is_subtype(left, NumericBase):
            raise InvalidType("Can only calculate max on numeric types", node)
        compare_types(left, right, node)

        return Reference.from_type(left, "return value")


class Clear(BuiltinFunctionDefinition):

    _id = "clear"

    def fetch_call_return(self, node: vy_ast.Call) -> None:
        validate_call_args(node, 1)
        var = get_definition_from_node(node.args[0])
        var.validate_clear(node.args[0])

        return None


class Concat(BuiltinFunctionDefinition):

    _id = "concat"

    def fetch_call_return(self, node: vy_ast.Call) -> Reference:
        validate_call_args(node, (2, float('inf')))
        type_list = [get_definition_from_node(i).type for i in node.args]

        if next((i for i in type_list if not is_subtype(i, (BytesBase, StringBase))), False):
            raise InvalidType("Concat values must be bytes or string", node)

        is_str = next((i for i in type_list if is_subtype(i, StringBase)), False)
        is_bytes = next((i for i in type_list if is_subtype(i, BytesBase)), False)
        if is_str and is_bytes:
            raise TypeMismatch("Cannot perform concatenation between bytes and string", node)

        return_type = get_builtin_type("bytes" if is_bytes else "string")
        return_type.set_length(sum(i.length for i in type_list))
        return Reference.from_type(return_type, "return value")


class MethodID(BuiltinFunctionDefinition):

    _id = "method_id"

    def evaluate(self, node: vy_ast.Call) -> vy_ast.Bytes:
        try:
            self.fetch_call_return(node)
        except CompilerPanic:
            pass

        sig = get_literal_or_raise(node.args[0]).value
        length = get_type_from_annotation(node.args[1]).length

        method_id = fourbytes_to_int(keccak256(sig.encode())[:4])
        value = method_id.to_bytes(length, "big")

        return vy_ast.Bytes.from_node(node, value=value)

    def fetch_call_return(self, node: vy_ast.Call) -> None:
        validate_call_args(node, 2)
        sig = get_literal_or_raise(node.args[0]).value
        if not isinstance(node.args[0], vy_ast.Str):
            raise InvalidType("method id must be given as a literal string", node.args[0])
        if " " in sig:
            raise TypeMismatch('Invalid function signature no spaces allowed.')
        return_type = get_type_from_annotation(node.args[1])
        if not is_subtype(return_type, BytesBase) or return_type.length not in (4, 32):
            raise InvalidType("return type must be bytes32 or bytes[4]", node.args[1])

        # this method should always be foldable, and any invalid user input
        # should raise from one of the previous checks
        raise CompilerPanic("method_id should have been folded")


class Extract32(BuiltinFunctionDefinition):

    _id = "extract32"

    def fetch_call_return(self, node: vy_ast.Call) -> Reference:
        validate_call_args(node, 2, ["type"])
        target, length = (get_definition_from_node(i).type for i in node.args[:2])

        compare_types(target, namespace['bytes'], node.args[0])
        compare_types(length, namespace['int128'], node.args[1])

        if node.keywords:
            return_type = get_type_from_annotation(node.keywords[0].value)
            expected = get_builtin_type({"address", "bytes32", "int128", "uint256"})
            compare_types(return_type, expected, node.keywords[0])

        else:
            return_type = get_builtin_type("bytes32")

        return Reference.from_type(return_type, "return value")


class RawLog(BuiltinFunctionDefinition):

    _id = "raw_log"

    def fetch_call_return(self, node: vy_ast.Call) -> None:
        validate_call_args(node, 2)
        if not isinstance(node.args[0], vy_ast.List) or len(node.args[0].elts) > 4:
            raise InvalidType(
                "Expecting a list of 0-4 topics as first argument", node.args[0]
            )
        if node.args[0].elts:
            log_type = get_definition_from_node(node.args[0]).type
            compare_types(log_type[0], namespace['bytes32'], node.args[0])
        compare_types(
            get_definition_from_node(node.args[1]).type,
            get_builtin_type({'bytes', 'bytes32'}),
            node.args[1]
        )
        return None


class Convert(BuiltinFunctionDefinition):

    # TODO this is just a wireframe, expand it with complete functionality
    # https://github.com/vyperlang/vyper/issues/1093

    _id = "convert"

    def fetch_call_return(self, node: vy_ast.Call) -> Reference:
        validate_call_args(node, 2)
        initial_type = get_definition_from_node(node.args[0]).type
        if not is_subtype(initial_type, ValueType):
            raise InvalidType(f"Cannot convert type '{initial_type}'", node.args[0])
        target_type = get_type_from_annotation(node.args[1])
        try:
            compare_types(initial_type, target_type, node)
        except TypeMismatch:
            pass
        else:
            # TODO remove this if once the requirement to convert literal integers is fixed
            if target_type._id != "uint256":
                raise InvalidType(f"Value and target type are both '{target_type}'", node)

        try:
            validation_fn = getattr(self, f"validate_to_{target_type._id}")
        except AttributeError:
            raise InvalidType(
                f"Unsupported destination type '{target_type}'", node.args[1]
            ) from None

        validation_fn(initial_type)

        return Reference.from_type(target_type, "return value")

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

    def validate_to_string(self, initial_type):
        pass

    def validate_to_bytes(self, initial_type):
        pass

    def validate_to_address(self, initial_type):
        pass

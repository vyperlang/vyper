from collections import (
    OrderedDict,
)

from vyper import (
    ast as vy_ast,
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
    BytesType,
    ValueType,
)
from vyper.context.utils import (
    check_call_args,
)
from vyper.exceptions import (
    InvalidLiteralException,
    StructureException,
)

# convert
# raw_call

# assert, raise


class BuiltinFunctionDefinition(BaseDefinition):

    def __init__(self, namespace):
        super().__init__(namespace, self._id)


class SimpleBuiltinDefinition(FunctionDefinition, BuiltinFunctionDefinition):

    def __init__(self, namespace):
        arguments = OrderedDict()
        for name, types in self._inputs:
            arguments[name] = get_builtin_type(namespace, types)
        return_type = get_builtin_type(namespace, self._return_type) if self._return_type else None
        return_var = Variable(namespace, f"{self._id}_return", return_type)
        FunctionDefinition.__init__(
            self, namespace, self._id, arguments, len(arguments), return_var
        )


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
    _inputs = [("b", "bytes")]
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

    def validate_call(self, node: vy_ast.Call):
        check_call_args(node, 2)
        if not isinstance(node.args[1], vy_ast.Str):
            # TODO standard way to indicate a value must be a literal?
            raise
        denom = next((v for k, v in self.wei_denoms.items() if node.args[1].value in k), False)
        if not denom:
            raise InvalidLiteralException(
                f"Invalid denomination '{node.args[1].value}', valid denominations are: "
                f"{', '.join(x[0] for x in self.wei_denoms)}",
                node.args[1]
            )
        return super().validate_call(node)


class Slice(SimpleBuiltinDefinition):

    _id = "slice"
    _inputs = [("b", {'bytes', 'bytes32', 'string'}), ('start', 'int128'), ('length', 'int128')]
    _return_type = None

    def validate_call(self, node: vy_ast.Call):
        super().validate_call(node)

        start, length = (get_value_from_node(self.namespace, i) for i in node.args[1:])
        if not isinstance(start, int) or start < 0:
            raise StructureException("Start must be a positive literal integer ", node.args[1])
        if not isinstance(length, int) or length < 1:
            raise StructureException(
                "Length must be a literal integer greater than zero", node.args[2]
            )

        input_type = get_type_from_node(self.namespace, node.args[0])
        return_length = length - start
        if isinstance(input_type, BytesType):
            return_type = get_builtin_type(self.namespace, ("bytes", return_length))
        else:
            return_type = get_builtin_type(self.namespace, ("string", return_length))

        return Variable(self.namespace, "slice_return", return_type)


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


class Min(BuiltinFunctionDefinition):

    _id = "min"

    def validate_call(self, node: vy_ast.Call):
        check_call_args(node, 2)
        left, right = (get_type_from_node(self.namespace, i) for i in node.args)
        if not hasattr(left, 'is_numeric'):
            raise StructureException("Can only calculate min on numeric types", node)
        compare_types(left, right, node)
        return Variable(self.namespace, "min_return", left)


class Max(BuiltinFunctionDefinition):

    _id = "max"

    def validate_call(self, node: vy_ast.Call):
        check_call_args(node, 2)
        left, right = (get_type_from_node(self.namespace, i) for i in node.args)
        if not hasattr(left, 'is_numeric'):
            raise StructureException("Can only calculate min on numeric types", node)
        compare_types(left, right, node)
        return Variable(self.namespace, "min_return", left)


class Clear(BuiltinFunctionDefinition):

    _id = "clear"

    def validate_call(self, node: vy_ast.Call):
        check_call_args(node, 1)
        get_type_from_node(self.namespace, node.args[0])
        return None


class AsUnitlessNumber(BuiltinFunctionDefinition):

    _id = "as_unitless_number"

    def validate_call(self, node: vy_ast.Call):
        check_call_args(node, 1)
        value = get_value_from_node(self.namespace, node.args[0])
        if not isinstance(getattr(value, 'type'), ValueType):
            raise StructureException("Not a value type", node.args[0])
        if not hasattr(value.type, 'unit'):
            raise StructureException(f"Type '{value.type}' has no unit", node.args[0])
        typ = type(value.type)(self.namespace)
        del typ.unit
        return Variable(self.namespace, "unitless_return", typ)


class Concat(BuiltinFunctionDefinition):

    _id = "concat"

    def validate_call(self, node: vy_ast.Call):
        check_call_args(node, (2, float('inf')))
        type_list = [get_type_from_node(self.namespace, i) for i in node.args]

        idx = next((i for i in type_list if not isinstance(i, BytesType)), None)
        if idx is not None:
            node = node.args[type_list.index(idx)]
            raise StructureException("Concat values must be bytes", node)

        length = sum(i.min_length for i in type_list)
        return_type = get_builtin_type(self.namespace, ("bytes", length))
        return Variable(self.namespace, "concat_return", return_type)


class MethodID(BuiltinFunctionDefinition):

    _id = "method_id"

    def validate_call(self, node: vy_ast.Call):
        check_call_args(node, 2)
        if not isinstance(node.args[0], vy_ast.Str):
            raise StructureException("method id must be given as a literal string", node.args[0])
        return_type = get_type_from_annotation(self.namespace, node.args[1])
        if not isinstance(return_type, BytesType) or return_type.length not in (4, 32):
            raise StructureException("return type must be bytes32 or bytes[4]", node.args[1])
        return Variable(self.namespace, "method_id_return", return_type)


class Extract32(BuiltinFunctionDefinition):

    _id = "extract32"

    def validate_call(self, node: vy_ast.Call):
        check_call_args(node, (2, 3))
        target, length = (get_type_from_node(self.namespace, i) for i in node.args[:2])

        compare_types(target, self.namespace['bytes'], node.args[0])
        compare_types(length, self.namespace['int128'], node.args[1])

        # TODO union type, default types, any type?
        if len(node.args) == 3:
            return_type = get_type_from_annotation(self.namespace, node.args[2])
            if return_type._id not in ("bytes32", "int128", "address"):
                raise StructureException()

        else:
            return_type = get_builtin_type(self.namespace, "bytes32")

        return Variable(self.namespace, "extract32_return", return_type)


class RawLog(BuiltinFunctionDefinition):

    _id = "raw_log"

    def validate_call(self, node: vy_ast.Call):
        check_call_args(node, 2)
        if not isinstance(node.args[0], vy_ast.List) or len(node.args[0].elts) > 4:
            raise StructureException(
                "Expecting a list of 0-4 topics as first argument", node.args[0].elts[4]
            )
        if node.args[0].elts:
            log_type = get_type_from_node(self.namespace, node.args[0])
            compare_types(log_type[0], self.namespace['bytes32'], node.args[0])
        compare_types(
            get_type_from_node(self.namespace, node.args[1]),
            self.namespace['bytes'],
            node.args[1]
        )
        return None

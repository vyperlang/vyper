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
from vyper.context.definitions.variable import (
    Variable,
)
from vyper.context.types import (  # compare_types,
    get_builtin_type,
    get_type_from_node,
)
from vyper.context.utils import (
    check_call_args,
)

# convert
# clear, as_wei_value, as_unitless_number, slice, concat, keccack256
# sha256, method_id, extract32, RLPList, raw_call, raw_log

# assert, raise


class BuiltinFunctionDefinition(BaseDefinition):

    def __init__(self, namespace):
        super().__init__(namespace, self._id, "builtin")


class SimpleBuiltinDefinition(FunctionDefinition, BuiltinFunctionDefinition):

    def __init__(self, namespace):
        arguments = OrderedDict()
        for name, types in self._inputs:
            arguments[name] = get_builtin_type(namespace, types)
        return_type = get_builtin_type(namespace, self._return_type) if self._return_type else None
        return_var = Variable(namespace, "", "builtin", return_type)
        FunctionDefinition.__init__(
            self, namespace, self._id, "builtin", arguments, len(arguments), return_var
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


class Clear(BuiltinFunctionDefinition):

    _id = "clear"

    def validate_call(self, node: vy_ast.Call):
        check_call_args(node, 1)
        get_type_from_node(self.namespace, node.args[0])
        return None

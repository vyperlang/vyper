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
from vyper.exceptions import (
    InvalidLiteralException,
)

# convert
# as_unitless_number, slice, concat, keccack256
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
                f"Invalid denomination: {denom}, valid denominations are: "
                f"{','.join(x[0] for x in self.wei_denoms)}",
                node.args[1]
            )
        return super().validate_call(node)

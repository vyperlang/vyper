from collections import (
    OrderedDict,
)

from vyper.context.definitions.bases import (
    FunctionDefinition,
)
from vyper.context.definitions.variable import (
    Variable,
)
from vyper.context.types import (
    get_builtin_type,
)

# convert
# clear, as_wei_value, as_unitless_number, slice, concat, keccack256
# sha256, method_id, extract32, RLPList, raw_call, raw_log

# assert, raise


class BuiltinFunction(FunctionDefinition):

    def __init__(
        self,
        namespace,
        name: str,
        arguments,
        arg_count,
        return_var,
    ):
        super().__init__(namespace, name, "builtin", arguments, arg_count, return_var)


class SimpleBuiltin(BuiltinFunction):

    def __init__(self, namespace):
        arguments = OrderedDict()
        for name, types in self._inputs:
            arguments[name] = get_builtin_type(namespace, types)
        return_type = get_builtin_type(namespace, self._return_type) if self._return_type else None
        return_var = Variable(namespace, "", "builtin", return_type)
        super().__init__(namespace, self._id, arguments, len(arguments), return_var)


class Floor(SimpleBuiltin):

    _id = "floor"
    _inputs = [("value", "decimal")]
    _return_type = "int128"


class Ceil(SimpleBuiltin):

    _id = "ceil"
    _inputs = [("value", "decimal")]
    _return_type = "int128"


class Len(SimpleBuiltin):

    _id = "len"
    _inputs = [("b", "bytes")]
    _return_type = "int128"


class AddMod(SimpleBuiltin):

    _id = "uint256_addmod"
    _inputs = [("a", "uint256"), ("b", "uint256"), ("c", "uint256")]
    _return_type = "uint256"


class MulMod(SimpleBuiltin):

    _id = "uint256_mulmod"
    _inputs = [("a", "uint256"), ("b", "uint256"), ("c", "uint256")]
    _return_type = "uint256"


class Sqrt(SimpleBuiltin):

    _id = "sqrt"
    _inputs = [("d", "decimal")]
    _return_type = "decimal"


class ECRecover(SimpleBuiltin):

    _id = "ecrecover"
    _inputs = [("hash", "bytes32"), ("v", "uint256"), ("r", "uint256"), ("s", "uint256")]
    _return_type = "address"


class ECAdd(SimpleBuiltin):

    _id = "ecadd"
    _inputs = [("a", ["uint256", "uint256"]), ("b", ["uint256", "uint256"])]
    _return_type = ["uint256", "uint256"]


class ECMul(SimpleBuiltin):

    _id = "ecmul"
    _inputs = [("point", ["uint256", "uint256"]), ("scalar", "uint256")]
    _return_type = ["uint256", "uint256"]


class Send(SimpleBuiltin):

    _id = "send"
    _inputs = [("to", "address"), ("value", ("uint256", "wei"))]
    _return_type = None


class SelfDestruct(SimpleBuiltin):

    _id = "selfdestruct"
    _inputs = [("to", "address")]
    _return_type = None


class AssertModifiable(SimpleBuiltin):

    _id = "assert_modifiable"
    _inputs = [("cond", "bool")]
    _return_type = None


class CreateForwarder(SimpleBuiltin):

    _id = "create_forwarder_to"
    _inputs = [("target", "address"), ("value", ("uint256", "wei"))]
    _return_type = "address"


class Blockhash(SimpleBuiltin):

    _id = "blockhash"
    _inputs = [("block_num", "uint256")]
    _return_type = "bytes32"

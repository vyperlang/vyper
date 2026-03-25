from vyper import ast as vy_ast
from vyper.compiler.settings import get_global_settings
from vyper.exceptions import (
    ArrayIndexException,
    CompilerPanic,
    FeatureException,
    InstantiationException,
    InvalidType,
    StructureException,
    UndeclaredDefinition,
    UnknownType,
)
from vyper.semantics.analysis.levenshtein_utils import get_levenshtein_error_suggestions
from vyper.semantics.data_locations import DataLocation
from vyper.semantics.namespace import get_namespace
from vyper.semantics.types.base import TYPE_T, VyperType

# TODO maybe this should be merged with .types/base.py


def type_from_abi(abi_type: dict) -> VyperType:
    """
    Return a type object from an ABI type definition.

    Arguments
    ---------
    abi_type : dict
       A type definition taken from the `input` or `output` field of an ABI.

    Returns
    -------
    BaseTypeDefinition
        Type definition object.
    """
    type_string = abi_type["type"]
    if type_string == "int168" and abi_type.get("internalType") == "decimal":
        type_string = "decimal"
    if type_string in ("string", "bytes"):
        type_string = type_string.capitalize()

    namespace = get_namespace()

    if "[" in type_string:
        # handle dynarrays, static arrays
        value_type_string, length_str = type_string.rsplit("[", maxsplit=1)
        try:
            length = int(length_str.rstrip("]"))
        except ValueError:
            raise UnknownType(f"ABI type has an invalid length: {type_string}") from None
        try:
            value_type = type_from_abi({"type": value_type_string})
        except UnknownType:
            raise UnknownType(f"ABI contains unknown type: {type_string}") from None
        try:
            sarray_t = namespace["$SArrayT"]
            return sarray_t(value_type, length)
        except InvalidType:
            raise UnknownType(f"ABI contains unknown type: {type_string}") from None

    else:
        try:
            t = namespace[type_string]
            if type_string in ("Bytes", "String"):
                # special handling for bytes, string, since
                # the type ctor is in the namespace instead of a concrete type.
                return t()
            return t
        except KeyError:
            raise UnknownType(f"ABI contains unknown type: {type_string}") from None


def type_from_annotation(
    node: vy_ast.VyperNode, location: DataLocation = DataLocation.UNSET
) -> VyperType:
    """
    Return a type object for the given AST node after validating its location.

    Arguments
    ---------
    node: VyperNode
        Vyper ast node from the `annotation` member of a `VariableDecl` or `AnnAssign` node.

    Returns
    -------
    VyperType
        Type definition object.
    """
    typ = _type_from_annotation(node)

    if location in typ._invalid_locations:
        location_str = "" if location is DataLocation.UNSET else f"in {location.name.lower()}"
        raise InstantiationException(f"{typ} is not instantiable {location_str}", node)

    # TODO: cursed import cycle!
    from vyper.semantics.types.primitives import DecimalT

    if isinstance(typ, DecimalT):
        # is there a better place to put this check?
        settings = get_global_settings()
        if settings and not settings.get_enable_decimals():
            raise FeatureException("decimals are not allowed unless `--enable-decimals` is set")

    return typ


def _type_from_annotation(node: vy_ast.VyperNode) -> VyperType:
    namespace = get_namespace()

    if isinstance(node, vy_ast.Tuple):
        tuple_t = namespace["$TupleT"]
        return tuple_t.from_annotation(node)

    if isinstance(node, vy_ast.Subscript):
        # ex. HashMap, DynArray, Bytes, static arrays
        if node.value.get("id") in ("HashMap", "Bytes", "String", "DynArray"):
            assert isinstance(node.value, vy_ast.Name)  # mypy hint
            type_ctor = namespace[node.value.id]
        else:
            # like, address[5] or int256[5][5]
            type_ctor = namespace["$SArrayT"]

        return type_ctor.from_annotation(node)

    # prepare a common error message
    err_msg = f"'{node.node_source_code}' is not a type!"

    if isinstance(node, vy_ast.Attribute):
        # ex. SomeModule.SomeStruct

        if isinstance(node.value, vy_ast.Attribute):
            module_or_interface = _type_from_annotation(node.value)
        elif isinstance(node.value, vy_ast.Name):
            try:
                module_or_interface = namespace[node.value.id]  # type: ignore
            except UndeclaredDefinition:
                raise InvalidType(err_msg, node) from None
        else:
            raise InvalidType(err_msg, node)

        if hasattr(module_or_interface, "module_t"):  # i.e., it's a ModuleInfo
            module_or_interface = module_or_interface.module_t

        if not isinstance(module_or_interface, VyperType):
            raise InvalidType(err_msg, node)

        if not module_or_interface._attribute_in_annotation:
            raise InvalidType(err_msg, node)

        type_t = module_or_interface.get_type_member(node.attr, node)  # type: ignore
        assert isinstance(type_t, TYPE_T)  # sanity check
        return type_t.typedef

    if not isinstance(node, vy_ast.Name):
        # maybe handle this somewhere upstream in ast validation
        raise InvalidType(err_msg, node)

    if node.id not in namespace:  # type: ignore
        hint = get_levenshtein_error_suggestions(node.node_source_code, namespace, 0.3)
        raise UnknownType(
            f"No builtin or user-defined type named '{node.node_source_code}'.", node, hint=hint
        ) from None

    typ_ = namespace[node.id]
    if hasattr(typ_, "from_annotation"):
        # cases where the object in the namespace is an uninstantiated
        # type object, ex. Bytestring or DynArray (with no length provided).
        # call from_annotation to produce a better error message.
        typ_.from_annotation(node)

    if hasattr(typ_, "module_t"):  # it's a ModuleInfo
        typ_ = typ_.module_t

    if not isinstance(typ_, VyperType):
        raise CompilerPanic(f"Not a type: {typ_}", node)

    return typ_


def get_index_value(node: vy_ast.VyperNode) -> int:
    """
    Return the literal value for a `Subscript` index.

    Arguments
    ---------
    node: vy_ast.VyperNode
        Vyper ast node from the `slice` member of a Subscript node.

    Returns
    -------
    int
        Literal integer value.
        In the future, will return `None` if the subscript is an Ellipsis
    """
    # this is imported to improve error messages
    # TODO: revisit this!
    from vyper.semantics.analysis.utils import get_possible_types_from_node

    node = node.reduced()

    if not isinstance(node, vy_ast.Int):
        # even though the subscript is an invalid type, first check if it's a valid _something_
        # this gives a more accurate error in case of e.g. a typo in a constant variable name
        try:
            get_possible_types_from_node(node)
        except StructureException:
            # StructureException is a very broad error, better to raise InvalidType in this case
            pass
        raise InvalidType("Subscript must be a literal integer", node)

    if node.value <= 0:
        raise ArrayIndexException("Subscript must be greater than 0", node)

    return node.value

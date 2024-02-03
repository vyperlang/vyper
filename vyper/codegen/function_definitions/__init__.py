from .external_function import generate_ir_for_external_function
from .internal_function import generate_ir_for_internal_function

__all__ = [generate_ir_for_internal_function, generate_ir_for_external_function]  # type: ignore

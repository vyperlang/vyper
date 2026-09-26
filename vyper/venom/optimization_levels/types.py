from typing import Any, Dict, Tuple, Union

from vyper.venom.passes.base_pass import IRPass

PassConfig = Union[type[IRPass], Tuple[type[IRPass], Dict[str, Any]]]

__all__ = ["PassConfig"]

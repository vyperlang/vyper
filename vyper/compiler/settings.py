import os
from typing import Optional

VYPER_COLOR_OUTPUT = os.environ.get("VYPER_COLOR_OUTPUT", "0") == "1"
VYPER_ERROR_CONTEXT_LINES = int(os.environ.get("VYPER_ERROR_CONTEXT_LINES", "1"))
VYPER_ERROR_LINE_NUMBERS = os.environ.get("VYPER_ERROR_LINE_NUMBERS", "1") == "1"

VYPER_TRACEBACK_LIMIT: Optional[int]

_tb_limit_str = os.environ.get("VYPER_TRACEBACK_LIMIT")
if _tb_limit_str is not None:
    VYPER_TRACEBACK_LIMIT = int(_tb_limit_str)
else:
    VYPER_TRACEBACK_LIMIT = None

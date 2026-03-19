import pytest

import vyper
from vyper.cli.vyper_ir import _parse_args


def test_version(capsys):
    with pytest.raises(SystemExit) as exc_info:
        _parse_args(["--version"])

    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert vyper.__long_version__ in captured.out

from vyper.ast.metadata import NodeMetadata
from vyper.exceptions import VyperException


def test_metadata_journal():
    m = NodeMetadata()

    m["x"] = 1
    try:
        with m.enter_typechecker_speculation():
            m["x"] = 2
            m["x"] = 3

            assert m["x"] == 3
            raise VyperException("dummy exception")

    except VyperException:
        pass

    # rollback upon exception
    assert m["x"] == 1

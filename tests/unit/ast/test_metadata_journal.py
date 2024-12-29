from vyper.ast.metadata import NodeMetadata
from vyper.exceptions import VyperException


def test_metadata_journal_basic():
    m = NodeMetadata()

    m["x"] = 1
    assert m["x"] == 1


def test_metadata_journal_commit():
    m = NodeMetadata()

    with m.enter_typechecker_speculation():
        m["x"] = 1

    assert m["x"] == 1


def test_metadata_journal_exception():
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


def test_metadata_journal_rollback_inner():
    m = NodeMetadata()

    m["x"] = 1
    with m.enter_typechecker_speculation():
        m["x"] = 2

        try:
            with m.enter_typechecker_speculation():
                m["x"] = 3
                m["x"] = 4  # test multiple writes

                assert m["x"] == 4
                raise VyperException("dummy exception")

        except VyperException:
            pass

    assert m["x"] == 2


def test_metadata_journal_rollback_outer():
    m = NodeMetadata()

    m["x"] = 1
    try:
        with m.enter_typechecker_speculation():
            m["x"] = 2

            with m.enter_typechecker_speculation():
                m["x"] = 3
                m["x"] = 4  # test multiple writes

            assert m["x"] == 4

            m["x"] = 5

            raise VyperException("dummy exception")

    except VyperException:
        pass

    assert m["x"] == 1

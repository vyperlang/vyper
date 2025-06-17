import contextlib
from typing import Any

from vyper.exceptions import VyperException


# a commit/rollback scheme for metadata caching. in the case that an
# exception is thrown and caught during type checking (currently, only
# during for loop iterator variable type inference), we can roll back
# any state updates due to type checking.
# this is implemented as a stack of changesets, because we need to
# handle nested rollbacks in the case of nested for loops
class _NodeMetadataJournal:
    _NOT_FOUND = object()

    def __init__(self):
        self._node_updates: list[dict[tuple[int, str, Any], NodeMetadata]] = []

    def register_update(self, metadata, k):
        KEY = (id(metadata), k)
        if KEY in self._node_updates[-1]:
            return
        prev = metadata.get(k, self._NOT_FOUND)
        self._node_updates[-1][KEY] = (metadata, prev)

    @contextlib.contextmanager
    def enter(self):
        self._node_updates.append({})
        try:
            yield
        except VyperException as e:
            # note: would be better to only catch typechecker exceptions here.
            self._rollback_inner()
            raise e from e
        else:
            self._commit_inner()

    def _rollback_inner(self):
        for (_, k), (metadata, prev) in self._node_updates[-1].items():
            if prev is self._NOT_FOUND:
                metadata.pop(k, None)
            else:
                metadata[k] = prev
        self._pop_inner()

    def _commit_inner(self):
        inner = self._pop_inner()

        if len(self._node_updates) == 0:
            return

        outer = self._node_updates[-1]

        # register with previous frame in case inner gets committed
        # but outer needs to be rolled back
        for (_, k), (metadata, prev) in inner.items():
            if (id(metadata), k) not in outer:
                outer[(id(metadata), k)] = (metadata, prev)

    def _pop_inner(self):
        return self._node_updates.pop()


class NodeMetadata(dict):
    """
    A data structure which allows for journaling.
    """

    _JOURNAL: _NodeMetadataJournal = _NodeMetadataJournal()

    def __setitem__(self, k, v):
        # if we are in a context where we need to journal, add
        # this to the changeset.
        if len(self._JOURNAL._node_updates) != 0:
            self._JOURNAL.register_update(self, k)

        super().__setitem__(k, v)

    @classmethod
    @contextlib.contextmanager
    def enter_typechecker_speculation(cls):
        with cls._JOURNAL.enter():
            yield

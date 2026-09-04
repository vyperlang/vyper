import contextlib

class NodeMetadata(dict):
    """
    The data structure which represents a Node's metadata
    """

    def __setitem__(self, k, v):

        super().__setitem__(k, v)


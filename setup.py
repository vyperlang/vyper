# -*- coding: utf-8 -*-

import re

from setuptools import setup


# strip local version
def _local_version_suffix(version):
    """
    Return +commit.{_hash} for non-tagged versions.
    Returns empty string for exact tag matches.
    """
    if version.exact:
        return ""
    # version.node is like "g073df5f1", strip the 'g' prefix
    node = version.node
    _hash = node.removeprefix("g")
    assert node != _hash, "There should always be a prefix"
    return f"+commit.{_hash}"


def _global_version(version):
    from setuptools_scm.version import guess_next_dev_version

    # strip `.devN` suffix since it is not semver compatible
    # minor regex hack to avoid messing too much with setuptools-scm internals
    version_str = guess_next_dev_version(version)
    return re.sub(r"\.dev\d+", "", version_str)


setup(
    use_scm_version={
        "local_scheme": _local_version_suffix,
        "version_scheme": _global_version,
        "write_to": "vyper/version.py",
    },
)

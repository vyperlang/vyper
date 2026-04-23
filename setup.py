# -*- coding: utf-8 -*-

import os
import re
import subprocess

from setuptools import setup


# strip local version
def _local_version(version):
    return ""


def _global_version(version):
    from setuptools_scm.version import guess_next_dev_version

    # strip `.devN` suffix since it is not semver compatible
    # minor regex hack to avoid messing too much with setuptools-scm internals
    version_str = guess_next_dev_version(version)
    return re.sub(r"\.dev\d+", "", version_str)


hash_file_rel_path = os.path.join("vyper", "vyper_git_commithash.txt")
hashfile = os.path.relpath(hash_file_rel_path)

# there is no way in setuptools-scm to get metadata besides the package
# version into version.py. (and we need that version to be PEP440 compliant
# in order to get it into pypi). so, add the commit hash to the package
# separately, in order so that we can add it to `vyper --version`.
try:
    commithash = subprocess.check_output("git rev-parse --short HEAD".split())
    commithash_str = commithash.decode("utf-8").strip()
    with open(hashfile, "w") as fh:
        fh.write(commithash_str)
except subprocess.CalledProcessError:
    pass


setup(
    use_scm_version={
        "local_scheme": _local_version,
        "version_scheme": _global_version,
        "write_to": "vyper/version.py",
    }
)


<img src="https://raw.githubusercontent.com/vyperlang/vyper/master/logo/vyper-logo-transparent.svg?sanitize=true" alt="" width="110">

[![Build Status](https://github.com/vyperlang/vyper/workflows/Test/badge.svg)](https://github.com/vyperlang/vyper/actions/workflows/test.yml)
[![Documentation Status](https://readthedocs.org/projects/vyper/badge/?version=latest)](http://vyper.readthedocs.io/en/latest/?badge=latest "ReadTheDocs")
[![Discord](https://img.shields.io/discord/969926564286459934.svg?label=%23vyper)](https://discord.gg/6tw7PTM7C2)

[![PyPI](https://badge.fury.io/py/vyper.svg)](https://pypi.org/project/vyper "PyPI")
[![Docker](https://img.shields.io/docker/cloud/build/vyperlang/vyper)](https://hub.docker.com/r/vyperlang/vyper "DockerHub")

[![Coverage Status](https://codecov.io/gh/vyperlang/vyper/branch/master/graph/badge.svg)](https://codecov.io/gh/vyperlang/vyper "Codecov")
[![Language grade: Python](https://github.com/vyperlang/vyper/workflows/CodeQL/badge.svg)](https://github.com/vyperlang/vyper/actions/workflows/codeql.yml)

# Getting Started
See [Installing Vyper](http://vyper.readthedocs.io/en/latest/installing-vyper.html) to install vyper.
See [Tools and Resources](https://github.com/vyperlang/vyper/wiki/Vyper-tools-and-resources) for an additional list of framework and tools with vyper support.
See [Documentation](http://vyper.readthedocs.io/en/latest/index.html) for the documentation and overall design goals of the Vyper language.

See [Learn.Vyperlang.org](https://learn.vyperlang.org/) for **learning Vyper by building a Pokémon game**.
See [try.vyperlang.org](https://try.vyperlang.org/) to use Vyper in a hosted jupyter environment!

**Note: Vyper is beta software, use with care**

# Installation
See the [Vyper documentation](https://vyper.readthedocs.io/en/latest/installing-vyper.html)
for build instructions.

# Compiling a contract
To compile a contract, use:
```bash
vyper your_file_name.vy
```
***generate bytecode***

    vyper -f bytecode file-name.vy > file-name.bin

***generate abi***

    vyper -f abi file-name.vy > file-name.abi

There is also an [online compiler](https://vyper.online/) available you can use to experiment with
the language and compile to ``bytecode`` and/or ``IR``.

**Note: While the vyper version of the online compiler is updated on a regular basis it might
be a bit behind the latest version found in the master branch of this repository.**

## Testing (using pytest)

(Complete [installation steps](https://vyper.readthedocs.io/en/latest/installing-vyper.html) first.)

```bash
make dev-init
python setup.py test
```

# Contributing
* See Issues tab, and feel free to submit your own issues
* Add PRs if you discover a solution to an existing issue
* For further discussions and questions, post in [Discussions](https://github.com/vyperlang/vyper/discussions) or talk to us on [Discord](https://discord.gg/6tw7PTM7C2)
* For more information, see [Contributing](http://vyper.readthedocs.io/en/latest/contributing.html)

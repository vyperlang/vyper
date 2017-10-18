####################
Compiling a Contract
####################
To compile a contract, use:
::
    viper yourFileName.v.py

.. note:: 
    Since .vy is not official a language supported by any syntax highlighters or linters,
    it is recommended to name your Viper file ending with `.v.py` in order to have Python syntax highlighting.

An `online compiler <https://viper.tools/>`_ is available as well, which lets you experiment with
the language without having to install Viper. The online compiler allows you to compile to ``bytecode`` and/or ``LLL``.

.. note::
    While the viper version of the online compiler is updated on a regular basis it might
    be a bit behind the latest version found in the master branch of the repository.

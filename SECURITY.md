# Security Policy

## Supported Versions

- each Vyper version in the range `<v0.1.0-beta.1, 0.3.10>` contains a high severity vulnerability
  - if developing with such versions, please read https://github.com/vyperlang/vyper/security/advisories to learn how to work around the vulnerabilities
- as of May 2024, the `0.4.0` release is the most secure and the most comprehensively reviewed one and is recommended for use in production environments
- if a compiler vulnerability is found, a new compiler version with a patch will be released. The vulnerable version itself is not updated.

## Compiler Audits

- Vyper is conducts recurring security audits with multiple firms. Additionally, a competitive audit with [CodeHawks](https://www.codehawks.com/contests/cll5rujmw0001js08menkj7hc) was conducted during the fall of 2023.
- all Vyper audits can be found in a separate repository: [vyperlang/audits](https://github.com/vyperlang/audits)


## Known Vyper Vulnerabilities

- The link below is a list of all publicly disclosed vulnerabilities and exposures.
Best Practices dictate that when we are first made aware of a potential vulnerability,
we take the precaution of assessing its potential impact to deployed projects first.
When we are confident that a disclosure will not impact known projects that use Vyper,
we will add an entry to the list of security advisories for posterity and reference by others.

  - list of publicly known vulnerabilities: https://github.com/vyperlang/vyper/security/advisories


## Bug Bounty Program
- as of May 2024, Vyper does not have a bug bounty program. It is planned to instantiate one in the near future.

## Reporting a Vulnerability

If you think you have found a security vulnerability caused by the compiler with a project that has used Vyper,
please report the vulnerability to the relevant project's security disclosure program prior
to reporting to us. Additionally, please submit the compiler vulnerability at https://github.com/vyperlang/vyper/security/advisories.

**Please Do Not Log An Issue** mentioning the vulnerability.


The Vyper team can also be reached via email at security@vyperlang.org. Our PGP key is:
```
-----BEGIN PGP PUBLIC KEY BLOCK-----
Version: OpenPGP.js v4.7.2
Comment: https://openpgpjs.org

xjMEXiC9KhYJKwYBBAHaRw8BAQdAMMsB1qaofcbuG5/4Hmm1GD8M+2lKJ50B
YI2G44/nquDNK3Z5cGVyLXNlY3VyaXR5QHBtLm1lIDx2eXBlci1zZWN1cml0
eUBwbS5tZT7CeAQQFgoAIAUCXiC9KgYLCQcIAwIEFQgKAgQWAgEAAhkBAhsD
Ah4BAAoJENARd3wFTk2lbdIBALELumbNOvueWQJSN8g+AYmb2i2XGDkuhWB0
ZK8maVfpAPwINHjx8vmNZ2T/aML2dpmaL7h2g13OTDjt1nYeTMVCD844BF4g
vSoSCisGAQQBl1UBBQEBB0A7Lb7v2tyRBAasuwwzF94OzrbqVybJ5cgxsO3F
N+XKBAMBCAfCYQQYFggACQUCXiC9KgIbDAAKCRDQEXd8BU5NpRLzAQC+gaZ6
lg4OrPFHOK9zYqbQ0zpx+tadKaEoo51jzsjCLgEAmp01XCX7/0Ln1TtUFzMy
fRy18qk7KR6zOg2RRch5gQQ=
=O37G
-----END PGP PUBLIC KEY BLOCK-----
```

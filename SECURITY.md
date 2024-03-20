# Security Policy

## Supported Versions

Vyper is currently in limited beta.
This means that we only support the latest release and that you may encounter issues using it.
It is un-audited software, use with caution.

## Audit reports

Vyper is constantly changing and improving.
This means the latest version available may not be audited.
We try to ensure the highest security code possible, but occasionally things slip through.

### Compiler Audits

At specific releases, we conduct audits with experienced security professionals to ensure that the codebase quality is high,
and that we minimize the chance of critical bugs as much as possible.

Here are the audits we have undergone in the past:

| Audit Type | Audit Date | Auditor | Version | Report Link |
| ---------- | ---------- | ------- | ------- | ----------- |
| Preliminary Review | October 28, 2019 | [ConsenSys Diligence](https://consensys.net/diligence/) | 0.1.0b13 | https://consensys.net/diligence/audits/2019/10/vyper/ |

### Major Project Audits

Please read prior audit reports for projects that use Vyper here:

<!-- Please use the tagged version if possible, or commit hash if a non-tagged version was used. -->

| Project | Version | Report Link |
| ------- | ------- | ----------- |
| [Uniswap](https://uniswap.io) | 35038d2 | https://medium.com/consensys-diligence/uniswap-audit-b90335ac007 |
| [Computable](https://github.com/computablelabs/computable) | 0.1.0b10 | https://github.com/trailofbits/publications/raw/master/reviews/computable.pdf |

## Known Vyper Vulnerabilities and Exposures (VVEs)

The link below is a list of all publicly disclosed vulnerabilities and exposures.
Best Practices dictate that when we are first made aware of a potential vulnerability,
we take the precaution of assessing it's potential impact to deployed projects first.
When we are confident that a disclosure will not impact known projects that use Vyper,
we will add an entry to the list of security advisories for posterity and reference by others.

https://github.com/vyperlang/vyper/security/advisories

## Reporting a Vulnerability

If you think you have found a security vulnerability with a project that has used Vyper,
please report the vulnerability to the relevant project's security disclosure program prior
to reporting to us. If one is not available, submit it at https://github.com/vyperlang/vyper/security/advisories.

**Please Do Not Log An Issue** mentioning the vulnerability.

If you have contacted the relevant project, or you have found something that you do not think affects
a particular project, please also email your vulnerability to security@vyperlang.org. Our PGP key is:
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

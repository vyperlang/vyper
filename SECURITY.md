# Security Policy

## Supported Versions

- it is recommended to follow the list of known [vulnerabilities](https://github.com/vyperlang/vyper/security/advisories) and stay up-to-date with the latest releases
  - as of May 2024, the `0.4.0` release is the most secure and the most comprehensively reviewed one and is recommended for use in production environments
- if a compiler vulnerability is found, a new compiler version with a patch will be released. The vulnerable version itself is not updated (see the examples below).
  - `example1`: suppose `0.4.0` is the latest version and a hypothetical vulnerability is found in `0.4.0`, then a patch will be released in `0.4.1`
  - `example2`: suppose `0.4.0` is the latest version and a hypothetical vulnerability is found both in `0.3.10` and `0.4.0`, then a patch will be released only in `0.4.1`

## Compiler Audits

- Vyper conducts recurring security audits with multiple firms. Additionally, a competitive audit with [CodeHawks](https://www.codehawks.com/contests/cll5rujmw0001js08menkj7hc) was conducted during the fall of 2023.
- all Vyper audits can be found in a separate repository: [vyperlang/audits](https://github.com/vyperlang/audits)


## Known Vyper Vulnerabilities

- The link below lists all publicly disclosed vulnerabilities and exposures.
Best Practices dictate that when we are first made aware of a potential vulnerability,
we take precautions by assessing its potential impact on deployed projects.
When we are confident that disclosure will not impact known projects that use Vyper,
we will add an entry to the list of security advisories for posterity and reference by others.

  - list of publicly known vulnerabilities: https://github.com/vyperlang/vyper/security/advisories


## Bug Bounty Program
- as of May 2024, Vyper does not have a bug bounty program. It is planned to instantiate one soon.

## Reporting a Vulnerability

- If you think you have found a security vulnerability caused by the compiler with a project that has used Vyper,
please report the vulnerability to the relevant project's security disclosure program before reporting to us. Additionally, please privately disclose the compiler vulnerability at https://github.com/vyperlang/vyper/security/advisories.

- **Please Do Not Log An Issue** mentioning the vulnerability.
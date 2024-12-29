# Security Policy

## Supported Versions

- it is recommended to follow the list of known [vulnerabilities](https://github.com/vyperlang/vyper/security/advisories) and stay up-to-date with the latest releases
  - as of May 2024, the [`0.4.0`](https://github.com/vyperlang/vyper/releases/tag/v0.4.0) release is the most comprehensively reviewed one and is recommended for use in production environments
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
- Vyper runs a bug bounty program via the Ethereum Foundation.
  - Bugs should be reported through the [Ethereum Foundation's bounty program](https://ethereum.org/bug-bounty).

### Scope
- Rules from the Ethereum Foundation's bug bounty program apply; for any questions please reach out [here](mailto:bounty@ethereum.org). Here we further clarify the scope of the Vyper bounty program.
- If a compiler bug affects production code, it is in scope (excluding known issues).
  - This includes bugs in older compiler versions still used in production.
- If a compiler bug does not currently affect production but is likely to in the future, it is in scope.
  - This mainly applies to the latest compiler release (e.g., a new release is available but contracts are not yet deployed with it).
  - Experimental features (e.g. `--experimental-codegen`) are out of scope, as they are not intended for production and are unlikely to affect production code.
  - Bugs in older compiler versions are generally out of scope, as they are no longer used for new contracts.
    - There might be exceptions, e.g., when an L2 doesn't support recent compiler releases. In such cases, it might be reasonable for an older version to be used. It is up to the discretion of the EF & Vyper team to decide if the bug is in scope.
- If a vulnerability affects multiple contracts, the whitehat is eligible for only one payout (though the severity of the bug may increase).
- Eligibility for project-specific bounties is independent of this bounty.
- [Security advisories](https://github.com/vyperlang/vyper/security/advisories) and [known issues](https://github.com/vyperlang/vyper/issues) are not eligible for the bounty program, as they are publicly disclosed and protocols should structure their contracts accordingly.
- Individuals or organizations contracted or engaged specifically for security development, auditing, or testing of this project are ineligible for the bounty program.

## Reporting a Vulnerability

- If you think you have found a security vulnerability caused by the compiler with a project that has used Vyper,
please report the vulnerability to the relevant project's security disclosure program before reporting to us. Additionally, please privately disclose the compiler vulnerability at https://github.com/vyperlang/vyper/security/advisories.

- **Please Do Not Log An Issue** mentioning the vulnerability.
# Security Policy

## Supported Versions

Vyper is currently in limited beta.
This means that we only support the latest release and that you may encounter issues using it.
It is un-audited software, use with caution.

If you have questions or concerns, please contact us on gitter:
[![Join the chat at https://gitter.im/bethereum/vyper](https://badges.gitter.im/ethereum/vyper.svg)](https://gitter.im/ethereum/vyper?utm_source=badge&utm_medium=badge&utm_campaign=pr-badge&utm_content=badge)

## Audit reports

Vyper has not been audited yet. When an audit is complete, we will list all previous reports here.

<!-- REMOVE WHEN COMPLETE
Vyper is constantly changing and improving.
This means the lastest version available may not be audited.
We try to ensure the highest security code possible, but occasionally things slip through.

At specific releases, we conduct audits with experienced security professionals to ensure that the codebase quality is high,
and that we minimize the chance of critical bugs as much as possible.

Here are the audits we have undergone in the past:

| Audit Date | Auditor | Version | Report Link |
| ---------- | ------- | ------- | ----------- |
-->

Please read prior audit reports for projects that use Vyper here:

<!-- Please use the tagged version if possible, or commit hash if a non-tagged version was used. -->

| Project | Version | Report Link |
| ------- | ------- | ----------- |
| Uniswap | 35038d2 | https://medium.com/consensys-diligence/uniswap-audit-b90335ac007 |

## Known Vyper Vulnerabilities and Exposures (VVEs)

The following is a list of all publicly disclosed vulnerabilities and exposures.
Best Practices dictate that when we are first made aware of a potential vulnerability,
we take the precaution of assessing it's potential impact to deployed projects first.
When we are confident that a disclosure will not impact known projects that use Vyper,
we will add an entry to this table for posterity and reference by others.

<!-- Please use the tagged version if possible, or commit hash if a non-tagged version was used. -->

| VVE | Description | Introduced | Fixed | Report Link |
| --- | ----------- | ---------- | ----- | ----------- |
| VVE-2019-0001 | Stack Exhaustion via Private Calls w/ Arrays | v0.1.0-beta.4 | v0.1.0-beta.10 | https://github.com/ethereum/vyper/issues/1418#issuecomment-496509570 |

## Reporting a Vulnerability

If you think you have found a security vulnerability with a project that has used Vyper,
please report the vulnerability to the relevant project's security disclosure program prior
to reporting to us. If one is not available, please email your vulnerability to security@ethereum.org

**Please Do Not Log An Issue** mentioning the vulnerability.

If you have contacted the relevant project, or you have found something that you do not think affects
a particular project, please also email your vulnerability to security@ethereum.org.
One of the staff security professionals will get back to you as soon as possible letting you know what
will happen next. You may even quality for the [bounty program](https://bounty.ethereum.org/).

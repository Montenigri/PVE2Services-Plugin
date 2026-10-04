# Security Policy

## Reporting a vulnerability

If you discover a security vulnerability in the PVE2Services plugins, please
report it responsibly.

**Do not open a public GitHub issue for security vulnerabilities.**

Report it privately through GitHub's
[Security Advisories](https://github.com/Montenigri/PVE2Services-Plugin/security/advisories/new)
on this repository. Include:

- a description of the vulnerability and its impact;
- steps to reproduce (proof of concept if possible);
- affected plugin(s) and version(s);
- a suggested fix, if you have one.

## Response timeline

- **Acknowledgment:** within 48 hours.
- **Initial assessment:** within 1 week.
- **Fix or mitigation:** depends on severity, typically within 2 weeks.

## Scope

This repository contains the first-party plugin sources. The core runtime,
authentication, CSRF and secret-encryption implementation live in the
[core repository](https://github.com/Montenigri/pve2service-core); report core
issues there.

Plugin-specific security requirements:

- Plugins must only expose **read-only** data to the assistant
  (`mcp.tools[].read_only: true`); mutating actions must never be offered.
- Secrets are encrypted at rest by `ConnectorConfig` (`SECRET_FIELDS`);
  never log secret values (`libs.audit.redact`).
- The **private** plugin signing key must never be committed; it lives in CI
  secrets (`PVE2_PLUGIN_SIGNING_KEY`) or a secure local store. Only the public
  half is committed in the core repository.

## Supported versions

| Version | Supported |
|---------|-----------|
| 0.1.x   | Yes       |

## Disclosure policy

We follow coordinated disclosure. Please give us reasonable time to address the
issue before public disclosure.

---
name: self-hosted-service-operator
description: Operate and verify self-hosted Docker or Podman Compose applications plus Windows services and systemd units. Use for local or LAN service deployment and lifecycle work; do not load an exhaustive catalog into context.
license: MIT
allowed-tools: [SelfHostedService, SystemAdmin, Repository, MCP, WebFetch]
metadata:
  references: [https://github.com/awesome-selfhosted/awesome-selfhosted]
  tags: [self-hosted, docker, podman, systemd, windows-services, operations, backup]
---

# Self-hosted service operator

Use the external catalog only to discover candidates for the user's stated need. Do not mirror or inject the full list into the prompt. Before recommending or installing a candidate, verify its current official repository, license, platform support, maintenance state, hardware needs, authentication model, backup documentation, and upgrade path.

## Operating contract

1. Inspect `SelfHostedService` capabilities and the device before choosing Docker/Podman Compose, a Windows service, or systemd. Do not install a container engine or expose a port unless the user approves that specific change.
2. Prefer the application's official deployment manifest. Keep secrets outside committed Compose files and conversation text. Never reuse a Jonathan/provider credential as an application password.
3. Register only a concrete, existing manifest or operating-system service. Include a local/LAN health URL and the smallest data/config paths needed for backup.
4. Before a risky update, inspect status and logs, create a downloadable backup, record the current image/package version, and identify the documented rollback command or pinned version.
5. Start, stop, restart, pull/update, and remove only through `SelfHostedService` or another explicit approved tool. Do not synthesize shell pipelines or execute install snippets copied from an untrusted catalog entry.
6. After a change, prove process/container state and health. Report ports, storage location, backup artifact, version, and any remaining manual authentication step. A reachable HTTP response is evidence of reachability, not proof that the application is correctly configured.

Use Jonathan's connector system or MCP for application-level API access after lifecycle health is established. Store credentials in the connector vault; the service manifest contains no password or token fields.

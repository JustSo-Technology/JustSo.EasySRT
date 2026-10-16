# JustSo.EasySRT

[EasySRT website](https://easusrt.justso.tech)

Linux-first SRT contribution sender with a FastAPI backend, React WebUI, a root-owned local control helper, and a `systemd`-managed `ffmpeg` runtime.

## Stack

- Backend: FastAPI, SQLModel, SQLite, session auth
- Frontend: React, TypeScript, Vite, Tailwind, TanStack Query
- Runtime: `ffmpeg`, `systemd`, root-owned Unix-socket helper for privileged host actions

> Public alpha candidate. Keep deployments on a trusted private network until
> you have configured HTTPS and reviewed [docs/deployment-security.md](docs/deployment-security.md).

## Documentation

- [Install on Ubuntu](docs/installation.md): one-command curl install, pinned versions, manual production build, updates and verification.
- [Configure EasySRT](docs/configuration.md): input, receiver, encoding, latency, saved presets and first-stream checklist.
- [Build from source / development](docs/development.md): locked dependencies, frontend/backend commands and local limitations.
- [Platform support](docs/platform-support.md): Ubuntu, Arch, Fedora, macOS and Windows.
- [Configuration import/export](docs/configuration-transfer.md): move presets safely, including legacy latency review.
- [Deployment security](docs/deployment-security.md): HTTPS, network access, secrets and privileged update policy.
- [Release procedure](docs/releasing.md).

## Quick start

Use a fresh Ubuntu Server 24.04 LTS VM and a sudo-capable account. The installer accepts Ubuntu 24.04 or newer; other operating systems are not supported production targets. It installs dependencies and builds EasySRT from source.

Use the [one-command installer](docs/installation.md#one-command-install), or follow the source-inspection and manual-build routes in the same guide. After installation, open the printed URL, create the first owner account and follow the [configuration guide](docs/configuration.md).

Any platform with a suitable browser can operate an EasySRT server remotely. Native sender/service installation is a separate compatibility question; see the [platform table](docs/platform-support.md).

## Platform roadmap

We are investigating native support for **macOS, Arch Linux and Fedora**.
These are exploratory plans, not currently supported installation targets;
there are no committed release dates. Ubuntu remains the primary deployment
target. See the [platform roadmap](docs/platform-support.md#platform-roadmap)
for the scope and validation required before support is announced.

## Licence and commercial use

JustSo.EasySRT is licensed under
[GNU AGPL version 3 only](LICENSE). If you modify it and make the modified
software available to users over a network, the AGPL requires you to offer
those users the corresponding source.

Separate commercial licensing is available from licensing@justso.dev.
The software licence does not grant rights to the JustSo or EasySRT marks;
see [TRADEMARKS.md](TRADEMARKS.md). Third-party components remain under their
own licences; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

Copyright © 2026 JUST SO GROUP PTY LTD, trading as JustSo. Technology.

## Contributing and security

See [CONTRIBUTING.md](CONTRIBUTING.md) and [CLA.md](CLA.md) before opening a
pull request. Report vulnerabilities privately to security@justso.dev as
described in [SECURITY.md](SECURITY.md).

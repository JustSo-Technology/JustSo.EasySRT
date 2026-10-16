# Platform support

[Documentation home](../README.md) · [Installation](installation.md)

This table describes the current repository, not general FFmpeg portability. A platform running Python/React does not necessarily support EasySRT's sender, privileged helper or updater.

| Host | Current deployment status | Practical route |
| --- | --- | --- |
| Ubuntu Server 24.04 LTS | Primary production target; earlier install/reinstall/update/rollback rehearsals are recorded in the readiness report | Use the Ubuntu installer, then validate your selected version with an isolated receiver |
| Newer Ubuntu | Accepted by the installer; not a claim of testing every release or CPU architecture | Rehearse installation and full stream/update lifecycle before operational use |
| Arch Linux | No supported installer or validated deployment | Run an Ubuntu VM, or develop a dedicated port |
| Fedora | No supported installer or validated deployment | Run an Ubuntu VM, or develop a dedicated port |
| macOS | Local UI/API development is possible; no native production sender/service deployment | Use an Ubuntu VM for streaming; use the browser to operate it |
| Windows | No native installer or validated sender/service deployment | Use an Ubuntu VM and access the WebUI from Windows |
| WSL2 | Not a validated deployment target, including distributions with systemd enabled | Treat as experimental; use a full Ubuntu VM for the documented path |

All these operating systems can access a deployed EasySRT instance through a browser and the permitted management network.

## Why the Ubuntu restriction exists

`ops/install-ubuntu.sh` explicitly checks Ubuntu >=24.04. Installation/update scripts use apt/dpkg, Ubuntu package names and NodeSource setup. Services require systemd, Linux paths/accounts/permissions, sudo, GNU utilities and a Unix-socket helper using Linux peer credentials. FFmpeg needs SRT support and the encoders selected by the profile.

Arch and Fedora already have Linux/systemd, so a port is plausible, but it must cover package names/managers, dependencies, account provisioning, service units, firewall policy, Fedora SELinux policy where applicable, privileged update isolation and rollback. Removing the OS check is not a port.

macOS would need replacements for systemd, Linux peer credentials, provisioning and host control. Windows would additionally need native service, IPC and permissions implementations. Neither is delivered by building the frontend or installing the Python backend.

## What must pass before adding a supported platform

For each named OS version and CPU architecture, validate clean install and repeat install, owner login and configuration, actual SRT receiver lock/audio, service stop/start/reboot, secure UI/updater access, update and failed-update rollback, and any claimed partner redundancy behavior. Maintain CI/package instructions for that platform. No cross-platform release promise or hardware minimum is made by this document.

## Platform roadmap

We are investigating native EasySRT support for **macOS, Arch Linux and Fedora**. These are exploratory plans, not currently supported installation targets or committed release dates.

- **macOS:** investigate native service management and permissions, with Homebrew as a potential distribution method. Evaluate unattended operation before login as well as desktop use.
- **Arch Linux:** investigate distribution-native dependency installation, systemd integration and a supported update/recovery workflow.
- **Fedora:** investigate distribution-native dependency installation, systemd integration, SELinux compatibility and a supported update/recovery workflow.

Each port must pass the installation, streaming, security and recovery validation described above before being advertised as supported. Ubuntu remains the primary deployment target while this work is investigated.

# Security Policy

Until the first stable release, security fixes are provided for the latest
published prerelease only.

Do not open a public issue for a vulnerability. Email security@justso.dev with
the affected version or commit, reproduction steps, likely impact, suggested
mitigation, and a safe contact method. We aim to acknowledge reports within
three business days and coordinate disclosure after a fix is available.

EasySRT is an administrative control plane. Keep the backend on loopback. Use
HTTPS, secure session cookies, trusted hosts, and firewall restrictions before
access from an untrusted network. Never expose the updater port publicly.

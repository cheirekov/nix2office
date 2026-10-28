# Personal settings and recovery: proposed next step

Nix and Home Manager reproduce the declared baseline. They do not restore
personal data, browser sessions or application accounts. The current assistant
does **not** create backups or scheduled jobs; this document defines a future
approach, separate from the experimental machine's no-backup workflow.

## Decide who owns each setting

| Data/settings | Owner and behavior today | Future recovery |
| --- | --- | --- |
| Packages, user/login policy, language, selected browser, MIME associations, supplied desktop shortcuts, declared XFCE settings | Nix/Home Manager reapply them at activation; GUI changes may be reset | Rebuild the pinned private flake; do not restore over managed files/symlinks |
| LibreOffice toolbar/profile | Initial Tabbed layout is seeded only when absent; later personal changes survive | Optionally restore the mutable LibreOffice profile with the app closed |
| Browser bookmarks/profile, dictionaries, personal XFCE preferences outside managed properties | Mutable user state | Explicit opt-in backup; browser profiles can contain cookies/tokens |
| Documents and other personal files | User data | Independently selected backup paths and retention |
| Nextcloud data and account state | Sync client and keyring | Sync is not versioned independent backup; avoid backing up caches or duplicating an entire remote account unintentionally |
| SOPS identities, runtime VPN identities/profiles, desktop keyring | Secrets with separate recovery requirements | Encrypted storage, restricted access, deliberate handling of credentials; never a public Git repository |

For a future implementation, use one encrypted restic repository per agreed
scope, with an explicit allowlist of paths, retention and destination. Keep its
password/recovery instructions independently available; do not make recovery
depend only on the lost machine. Start with manual backup/restore, then add a
schedule only when requested. Exclude caches, Nix store, build results, transient
sockets, mounted remote shares and managed symlinks. Include authentication
state only with an explicit decision, since it can grant access to accounts.

Restore to a staging directory first. On a replacement machine: provision its
own host secrets, rebuild the same pinned baseline, sign out and close the
relevant apps, then selectively copy mutable data as the correct user. Check
ownership if the login or UID changed. Restoring XFCE channel XML wholesale can
conflict with Home Manager; prefer importing only undeclared properties with
xfconfd stopped. Managed properties still return to their declared values at
the next activation. Never overwrite system passwords or VPN device identity
incidentally while restoring preferences.

A first recovery check should restore one bookmark, one LibreOffice preference
and a sample document into a disposable profile. That establishes that the
selected data, encryption key and ownership work before relying on a schedule.

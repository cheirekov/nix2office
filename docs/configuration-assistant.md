# A simpler setup interface (proposal)

The current initializer asks for host, disk, administrator network and SSH key,
but the desktop username and application set are fixed in the office module.
Changing those still requires editing Nix. A template alone would not remove
that limitation.

The next interface should be a small terminal assistant plus an editable
`machine.toml` inside the ignored private deployment. It would generate the same
ordinary Nix configuration that advanced users can inspect and extend. No
additional background service is needed on the office machine.

This is an illustrative format, not an accepted input to today's initializer:

```toml
hostname = "office-pc"
desktop_user = "maria"
profile = "light"
browser = "firefox-esr"
office = "libreoffice"
nextcloud = true
boot_splash = true

[sharing]
mode = "client" # proposed choices: off, client, both
workgroup = "WORKGROUP"
```

The assistant should read hardware facts and offer a recommendation before the
user chooses applications. The initial guidance would be conservative:

| Hardware | Suggested starting point |
| --- | --- |
| Around 2 GiB RAM and an older dual-core CPU | Light XFCE profile; few browser tabs; selective Nextcloud sync |
| 4 GiB RAM | Same profile with more room for simultaneous applications |
| 8 GiB or more | Choose applications primarily by compatibility and preference |

These are starting recommendations, not measured capacity guarantees. The
current experimental machine gives a useful reference for the light profile.
Browser alternatives need their own packaging and integration checks; there
is no measured Firefox/Brave/Chromium memory ranking in this project.

Passwords must never be TOML values, command-line arguments or Nix strings.
The assistant would collect them through hidden terminal prompts, hash them,
and encrypt the hashes for sops-nix. Private age identities stay outside Git
and the Nix store. The public template contains no deployment-specific values.

For Windows sharing, client access is already included. The optional server
mode should additionally ask for the directory, allowed users, write access
and trusted network, then generate an authenticated Samba share. It must not
silently create a guest share or expose every user directory. A workgroup name
groups machines; it does not grant access or join an Active Directory domain.

Implementation order:

1. Add module options for the desktop username, browser and optional application
   groups. Update Home Manager and secret wiring to use those options together.
2. Teach the private deployment initializer to read and validate the TOML file,
   while retaining explicit command-line use.
3. Add interactive questions, hardware recommendations and a review of the
   selected disk and generated configuration before installation.

For the existing installation, changing the desktop username would need a
separate migration of the home directory, ownership and keyring. This proposal
does not perform that migration or alter the installed user's identity.

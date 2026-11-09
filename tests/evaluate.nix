# Evaluate integrations without building every browser or activating a machine.
{
  root,
  flake ? builtins.getFlake root,
}:
let
  f = flake;
  lib = f.inputs.nixpkgs.lib;
  cases = {
    firefox = {
      role = "office";
      browser = "firefox-esr";
      office = "libreoffice";
      pdf = "pdfarranger";
      boot = "bios";
      bg = "phonetic";
      services = true;
      gpuDriver = "i915";
    };
    chromium = {
      role = "office";
      browser = "chromium";
      office = "onlyoffice";
      pdf = "xournalpp";
      boot = "uefi";
      bg = "bds";
      services = false;
    };
    brave = {
      role = "office";
      browser = "brave";
      office = "libreoffice";
      pdf = "both";
      boot = "bios";
      bg = "bds";
      services = false;
      gpuDriver = "amdgpu";
    };
    chrome = {
      role = "office";
      browser = "google-chrome";
      office = "none";
      pdf = "none";
      boot = "uefi";
      bg = "phonetic";
      services = false;
      gpuDriver = "nouveau";
    };
    hybrid = {
      role = "hybrid";
      browser = "firefox-esr";
      office = "libreoffice";
      pdf = "pdfarranger";
      boot = "bios";
      bg = "phonetic";
      services = false;
      thinProfiles = [
        {
          name = "win";
          host = "192.0.2.10";
          user = "accountant";
          remoteApps = [
            "Accounting"
            "C:\\Program Files\\ExpectaClient.exe"
          ];
        }
      ];
    };
    thin = {
      role = "thin";
      browser = "firefox-esr";
      office = "libreoffice";
      pdf = "pdfarranger";
      boot = "bios";
      bg = "phonetic";
      services = false;
      thinProfiles = [
        {
          name = "win";
          host = "192.0.2.10";
          user = "kiosk";
        }
      ];
    };
  };
  evaluate =
    name: variant:
    let
      role = variant.role or "office";
      thin = role == "thin";
      office = role != "thin";
      hybrid = role == "hybrid";
      c =
        (lib.nixosSystem {
          system = "x86_64-linux";
          modules = [
            f.nixosModules.office
            f.nixosModules.disk
            (f.lib.machineModule ../examples/machine.toml)
            ({ lib, ... }: {
              users.allowNoPasswordLogin = true; # Locked accounts in evaluation only.
              nix2office = {
                role = lib.mkForce role;
                thinClient = {
                  credentials = lib.mkForce (variant.thinCredentials or "interactive");
                  profiles = lib.mkForce (variant.thinProfiles or [ ]);
                };
                adminNetwork = lib.mkForce (if variant.services then "0.0.0.0/0" else "192.0.2.0/24");
                adminAuthorizedKeys = lib.mkForce [ "ssh-ed25519 AAAA evaluation-only" ];
                hardware.gpuDriver = lib.mkForce (variant.gpuDriver or "unknown");
                fonts.microsoftCore = lib.mkForce variant.services;
                remoteSupport = {
                  mode = lib.mkForce (
                    if variant.services then
                      "consent"
                    else if name == "chrome" then
                      "unattended"
                    else
                      "off"
                  );
                  idServer = lib.mkForce "rustdesk.example.org";
                  relayServer = lib.mkForce "rustdesk.example.org";
                  publicKey = lib.mkForce "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=";
                  ipWhitelist = lib.mkForce (if variant.services then [ "0.0.0.0/0" ] else [ ]);
                  directIpAccess = lib.mkForce variant.services;
                };
                tools.comma.enable = lib.mkForce variant.services;
                apps.extra = lib.mkForce (lib.optional variant.services "remmina");
                devices.bluetooth = lib.mkForce variant.services;
                devices.unfreeFirmware = lib.mkForce variant.services;
                apps.artcraft = lib.mkForce variant.services;
                apps.browser = lib.mkForce variant.browser;
                apps.office = lib.mkForce variant.office;
                apps.pdfEditor = lib.mkForce variant.pdf;
                apps.nextcloud = lib.mkForce variant.services;
                bootMode = lib.mkForce variant.boot;
                keyboard.bulgarian = lib.mkForce variant.bg;
                sharing.network = lib.mkForce (if variant.services then "0.0.0.0/0" else "192.0.2.0/24");
                sharing.mode = lib.mkForce (if variant.services then "both" else "client");
                vpn.tailscale = lib.mkForce variant.services;
                vpn.zerotier = lib.mkForce variant.services;
                vpn.zerotierNetworks = lib.mkForce (lib.optional variant.services "0123456789abcdef");
              };
            })
          ];
        }).config;
      home = c.home-manager.users.maria;
      desktop =
        (import ../lib/applications.nix {
          pkgs = c._module.args.pkgs;
          apps = c.nix2office.apps;
        }).browser.desktop;
    in
    assert c.users.users.maria.description == "Мария Димитрова";
    assert !(builtins.hasAttr "office" c.users.users);
    assert home.nix2office.user.email == "maria@example.org";
    assert c.services.xserver.xkb.variant == (if variant.bg == "bds" then "," else ",phonetic");
    assert c.services.xserver.desktopManager.xfce.enable == office;
    assert c.services.xserver.windowManager.openbox.enable == thin;
    assert c.services.displayManager.autoLogin.enable == thin;
    assert !thin || c.services.displayManager.autoLogin.user == "maria";
    assert c.services.displayManager.defaultSession == (if office then "xfce" else "none+openbox");
    assert
      (builtins.elem "freerdp" (map lib.getName c.environment.systemPackages)) == (role != "office");
    assert c.services.pcscd.enable == (role != "office");
    assert !thin || builtins.hasAttr "openbox/menu.xml" home.xdg.configFile;
    assert !thin || lib.hasInfix "--wait-network-timeout" home.xdg.configFile."openbox/autostart".text;
    assert !thin || builtins.elem "xterm" (map lib.getName c.environment.systemPackages);
    assert
      !thin || builtins.elem "network-manager-applet" (map lib.getName c.environment.systemPackages);
    assert !office || home.xdg.mimeApps.defaultApplications."x-scheme-handler/https" == [ desktop ];
    assert c.hardware.bluetooth.enable == variant.services;
    assert c.services.blueman.enable == variant.services;
    assert c.hardware.enableAllFirmware == variant.services;
    assert
      (builtins.elem "intel-vaapi-driver" (map lib.getName c.hardware.graphics.extraPackages))
      == ((variant.gpuDriver or "unknown") == "i915");
    assert
      (builtins.elem "mesa" (map lib.getName c.hardware.graphics.extraPackages))
      == (builtins.elem (variant.gpuDriver or "unknown") [
        "amdgpu"
        "radeon"
      ]);
    assert
      (builtins.elem "libva-vdpau-driver" (map lib.getName c.hardware.graphics.extraPackages))
      == ((variant.gpuDriver or "unknown") == "nouveau");
    assert !office || builtins.elem "carlito" (map lib.getName c.fonts.packages);
    assert !office || builtins.elem "caladea" (map lib.getName c.fonts.packages);
    assert
      !office || (builtins.elem "corefonts" (map lib.getName c.fonts.packages)) == variant.services;
    assert
      !office
      || (builtins.elem "remmina" (map lib.getName c.environment.systemPackages)) == variant.services;
    assert
      !office
      ||
        (builtins.elem "nix2office-comma-small-db" (map lib.getName c.environment.systemPackages))
        == variant.services;
    assert
      !office
      || (builtins.hasAttr "rustdesk" c.systemd.services) == (variant.services || name == "chrome");
    assert !office || !(builtins.hasAttr "nix2office-rustdesk" home.systemd.user.services);
    assert
      !office
      || !(builtins.hasAttr "rustdesk" c.systemd.services)
      || c.systemd.services.rustdesk.serviceConfig.User == "root";
    assert c.services.openssh.enable;
    assert !c.services.openssh.openFirewall;
    assert !c.services.openssh.settings.PasswordAuthentication;
    assert !c.services.openssh.settings.KbdInteractiveAuthentication;
    assert c.services.openssh.settings.PermitRootLogin == "no";
    assert lib.hasInfix (
      "ip saddr " + c.nix2office.adminNetwork + " tcp dport 22 accept"
    ) c.networking.firewall.extraInputRules;
    assert (c.nix2office.sharing.network == "0.0.0.0/0") == variant.services;
    assert c.services.samba.enable == variant.services;
    assert (builtins.hasAttr "samba-nmbd" c.systemd.services) == variant.services;
    assert (builtins.hasAttr "wsdd" c.systemd.services) == variant.services;
    assert
      lib.hasInfix (
        "ip saddr " + c.nix2office.sharing.network + " tcp dport 139 accept"
      ) c.networking.firewall.extraInputRules == variant.services;
    assert
      lib.hasInfix (
        "ip saddr " + c.nix2office.sharing.network + " udp dport 137 accept"
      ) c.networking.firewall.extraInputRules == variant.services;
    assert
      lib.hasInfix (
        "ip saddr " + c.nix2office.sharing.network + " udp dport 3702 accept"
      ) c.networking.firewall.extraInputRules == variant.services;
    assert
      lib.hasInfix (
        "ip saddr " + c.nix2office.sharing.network + " tcp dport 5357 accept"
      ) c.networking.firewall.extraInputRules == variant.services;
    assert
      lib.hasInfix "ip saddr 0.0.0.0/0 tcp dport 21118 accept" c.networking.firewall.extraInputRules
      == variant.services;
    assert c.services.tailscale.enable == variant.services;
    assert c.services.zerotierone.enable == variant.services;
    assert
      !office || (builtins.hasAttr "autostart/nextcloud.desktop" home.xdg.configFile) == variant.services;
    assert c.boot.loader.systemd-boot.enable == (variant.boot == "uefi");
    assert !hybrid || builtins.hasAttr "rdp-full-1" home.xdg.desktopEntries;
    assert !hybrid || builtins.hasAttr "rdp-app-win-1" home.xdg.desktopEntries;
    assert !hybrid || home.xdg.desktopEntries."rdp-app-win-1".name == "Accounting";
    assert !hybrid || home.xdg.desktopEntries."rdp-app-win-2".name == "ExpectaClient";
    assert !hybrid || builtins.hasAttr "rdp-shell-win-1" home.xdg.desktopEntries;
    assert !hybrid || home.xdg.desktopEntries."rdp-shell-win-1".name == "ExpectaClient (Alternate shell)";
    assert !hybrid || lib.hasInfix "--shell" home.xdg.desktopEntries."rdp-shell-win-1".exec;
    assert !thin || builtins.hasAttr "rdp-full-1" home.xdg.desktopEntries;
    {
      drv = c.system.build.toplevel.drvPath;
      inherit desktop;
      boot = variant.boot;
      keyboard = variant.bg;
      inherit (variant) office;
    };
in
lib.mapAttrs evaluate cases

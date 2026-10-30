# Evaluate integrations without building every browser or activating a machine.
{ root }:
let
  f = builtins.getFlake root;
  lib = f.inputs.nixpkgs.lib;
  cases = {
    firefox = {
      browser = "firefox-esr";
      office = "libreoffice";
      pdf = "pdfarranger";
      boot = "bios";
      bg = "phonetic";
      services = true;
    };
    chromium = {
      browser = "chromium";
      office = "onlyoffice";
      pdf = "xournalpp";
      boot = "uefi";
      bg = "bds";
      services = false;
    };
    brave = {
      browser = "brave";
      office = "libreoffice";
      pdf = "both";
      boot = "bios";
      bg = "bds";
      services = false;
    };
    chrome = {
      browser = "google-chrome";
      office = "none";
      pdf = "none";
      boot = "uefi";
      bg = "phonetic";
      services = false;
    };
  };
  evaluate =
    name: variant:
    let
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
                adminNetwork = lib.mkForce (if variant.services then "0.0.0.0/0" else "192.0.2.0/24");
                adminAuthorizedKeys = lib.mkForce [ "ssh-ed25519 AAAA evaluation-only" ];
                fonts.microsoftCore = lib.mkForce variant.services;
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
    assert home.xdg.mimeApps.defaultApplications."x-scheme-handler/https" == [ desktop ];
    assert c.services.xserver.xkb.variant == (if variant.bg == "bds" then "," else ",phonetic");
    assert c.hardware.bluetooth.enable == variant.services;
    assert c.services.blueman.enable == variant.services;
    assert c.hardware.enableAllFirmware == variant.services;
    assert builtins.elem "carlito" (map lib.getName c.fonts.packages);
    assert builtins.elem "caladea" (map lib.getName c.fonts.packages);
    assert (builtins.elem "corefonts" (map lib.getName c.fonts.packages)) == variant.services;
    assert (builtins.elem "remmina" (map lib.getName c.environment.systemPackages)) == variant.services;
    assert
      (builtins.elem "nix2office-comma-small-db" (map lib.getName c.environment.systemPackages))
      == variant.services;
    assert c.services.openssh.enable;
    assert !c.services.openssh.openFirewall;
    assert !c.services.openssh.settings.PasswordAuthentication;
    assert !c.services.openssh.settings.KbdInteractiveAuthentication;
    assert c.services.openssh.settings.PermitRootLogin == "no";
    assert lib.hasInfix "ip saddr ${c.nix2office.adminNetwork} tcp dport 22 accept"
      c.networking.firewall.extraInputRules;
    assert c.nix2office.sharing.network != "0.0.0.0/0";
    assert c.services.samba.enable == variant.services;
    assert c.services.tailscale.enable == variant.services;
    assert c.services.zerotierone.enable == variant.services;
    assert (builtins.hasAttr "autostart/nextcloud.desktop" home.xdg.configFile) == variant.services;
    assert c.boot.loader.systemd-boot.enable == (variant.boot == "uefi");
    {
      drv = c.system.build.toplevel.drvPath;
      inherit desktop;
      boot = variant.boot;
      keyboard = variant.bg;
      inherit (variant) office;
    };
in
lib.mapAttrs evaluate cases

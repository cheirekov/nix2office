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

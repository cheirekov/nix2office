file:
{ lib, ... }:
let
  m = builtins.fromTOML (builtins.readFile file);
  apps = m.apps or { };
  vpn = m.vpn or { };
  admin = m.admin or { };
  hardware = m.hardware or { };
  sharing = m.sharing or { };
  allowed = {
    root = [
      "version"
      "hostname"
      "disk"
      "boot_mode"
      "profile"
      "boot_splash"
      "user"
      "apps"
      "keyboard"
      "sharing"
      "vpn"
      "admin"
      "hardware"
    ];
    user = [
      "name"
      "full_name"
      "email"
    ];
    apps = [
      "browser"
      "office"
      "pdf_editor"
      "nextcloud"
    ];
    keyboard = [ "bulgarian" ];
    sharing = [
      "mode"
      "workgroup"
      "folder"
      "network"
      "read_only"
    ];
    vpn = [
      "wireguard"
      "tailscale"
      "zerotier"
      "zerotier_networks"
    ];
    admin = [
      "network"
      "ssh_public_key"
    ];
    hardware = [
      "cpu"
      "cpu_vendor"
      "memory_mib"
      "threads"
      "boot_mode"
      "initrd_modules"
    ];
  };
  sections = {
    root = m;
    user = m.user;
    keyboard = m.keyboard or { };
    inherit
      apps
      vpn
      admin
      hardware
      sharing
      ;
  };
in
{
  assertions =
    lib.mapAttrsToList (name: value: {
      assertion = lib.subtractLists allowed.${name} (builtins.attrNames value) == [ ];
      message = "Unknown machine.toml field in ${name}. Passwords and private keys never belong in this file.";
    }) sections
    ++ [
      {
        assertion = m.version == 1;
        message = "Unsupported machine.toml version.";
      }
      {
        assertion = builtins.elem (m.profile or "light") [
          "light"
          "standard"
        ];
        message = "Unknown machine.toml profile.";
      }
      {
        assertion = lib.all (
          x:
          builtins.elem x [
            "i915"
            "xe"
            "amdgpu"
            "nouveau"
          ]
        ) (hardware.initrd_modules or [ ]);
        message = "Unsupported early graphics driver in machine.toml.";
      }
    ];
  networking.hostName = m.hostname;
  nix2office = {
    diskDevice = m.disk;
    bootMode = m.boot_mode;
    bootSplash.enable = m.boot_splash or true;
    user = {
      name = m.user.name;
      fullName = m.user.full_name;
      email = m.user.email or "";
    };
    keyboard.bulgarian = (m.keyboard or { }).bulgarian or "phonetic";
    apps = {
      browser = apps.browser or "firefox-esr";
      office = apps.office or "libreoffice";
      pdfEditor =
        apps.pdf_editor or (if (m.profile or "light") == "light" then "pdfarranger" else "both");
      nextcloud = apps.nextcloud or true;
    };
    sharing = {
      mode = sharing.mode or "client";
      workgroup = sharing.workgroup or "WORKGROUP";
      folder = sharing.folder or "Shared";
      network = sharing.network or "192.0.2.0/24";
      readOnly = sharing.read_only or false;
    };
    vpn = {
      wireguard = vpn.wireguard or true;
      tailscale = vpn.tailscale or false;
      zerotier = vpn.zerotier or false;
      zerotierNetworks = vpn.zerotier_networks or [ ];
    };
    adminNetwork = admin.network or "192.0.2.0/24";
    adminAuthorizedKeys = lib.optional ((admin.ssh_public_key or "") != "") admin.ssh_public_key;
    hardware.cpuVendor = hardware.cpu_vendor or "unknown";
  };
  boot.initrd.kernelModules = hardware.initrd_modules or [ ];
}

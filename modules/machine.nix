file:
{ lib, ... }:
let
  m = builtins.fromTOML (builtins.readFile file);
  apps = m.apps or { };
  vpn = m.vpn or { };
  admin = m.admin or { };
  hardware = m.hardware or { };
  sharing = m.sharing or { };
  performance = m.performance or { };
  allowed = {
    root = [
      "version"
      "hostname"
      "disk"
      "boot_mode"
      "profile"
      "boot_splash"
      "performance"
      "user"
      "apps"
      "keyboard"
      "sharing"
      "vpn"
      "admin"
      "hardware"
      "devices"
      "fonts"
      "remote_support"
      "tools"
    ];
    user = [
      "name"
      "full_name"
      "email"
    ];
    performance = [ "cpu_governor" ];
    remote_support = [
      "mode"
      "id_server"
      "relay_server"
      "public_key"
    ];
    tools = [ "comma" ];
    fonts = [
      "microsoft_core"
      "office_fallbacks"
    ];
    devices = [
      "bluetooth"
      "unfree_firmware"
    ];
    apps = [
      "browser"
      "office"
      "pdf_editor"
      "nextcloud"
      "artcraft"
      "extra"
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
      "cpu_family"
      "cpu_model"
      "cpu_max_mhz"
      "frequency_drivers"
      "frequency_governors"
      "frequency_current_governors"
      "memory_mib"
      "threads"
      "boot_mode"
      "initrd_modules"
      "pci_ids"
      "usb_ids"
      "bluetooth_detected"
    ];
  };
  sections = {
    root = m;
    devices = m.devices or { };
    fonts = m.fonts or { };
    remote_support = m.remote_support or { };
    tools = m.tools or { };
    user = m.user;
    keyboard = m.keyboard or { };
    inherit
      apps
      vpn
      admin
      hardware
      sharing
      performance
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
            "radeon"
            "nouveau"
          ]
        ) (hardware.initrd_modules or [ ]);
        message = "Unsupported early graphics driver in machine.toml.";
      }
      {
        assertion =
          (performance.cpu_governor or "auto") == "auto"
          || (hardware.frequency_governors or [ ]) == [ ]
          || builtins.elem performance.cpu_governor hardware.frequency_governors;
        message = "The requested CPU governor was unavailable in the target snapshot; re-probe before changing it.";
      }
    ];
  networking.hostName = m.hostname;
  nix2office = {
    remoteSupport = {
      mode = (m.remote_support or { }).mode or "off";
      idServer = (m.remote_support or { }).id_server or "";
      relayServer = (m.remote_support or { }).relay_server or "";
      publicKey = (m.remote_support or { }).public_key or "";
    };
    tools.comma.enable = (m.tools or { }).comma or false;
    fonts.microsoftCore = (m.fonts or { }).microsoft_core or false;
    fonts.officeFallbacks = (m.fonts or { }).office_fallbacks or true;
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
      artcraft = apps.artcraft or false;
      extra = apps.extra or [ ];
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
    performance.cpuGovernor = performance.cpu_governor or "auto";
  };
  nix2office.devices = {
    bluetooth = (m.devices or { }).bluetooth or false;
    unfreeFirmware = (m.devices or { }).unfree_firmware or false;
  };
  boot.initrd.kernelModules = hardware.initrd_modules or [ ];
}

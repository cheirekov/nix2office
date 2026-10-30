{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.nix2office;
  server = cfg.sharing.mode == "both";
  sharePath = "/home/${cfg.user.name}/${cfg.sharing.folder}";
in
{
  options.nix2office.sharing = {
    mode = lib.mkOption {
      type = lib.types.enum [
        "client"
        "both"
      ];
      default = "client";
      description = "SMB client only, or client plus an authenticated server share.";
    };
    workgroup = lib.mkOption {
      type = lib.types.strMatching "[A-Za-z0-9][A-Za-z0-9_-]{0,14}";
      default = "WORKGROUP";
      description = "Windows workgroup, not an Active Directory domain.";
    };
    folder = lib.mkOption {
      type = lib.types.strMatching "[A-Za-z0-9][A-Za-z0-9_-]{0,63}";
      default = "Shared";
      description = "Dedicated shared folder inside the desktop user's home.";
    };
    network = lib.mkOption {
      type = lib.types.strMatching "[0-9.]+/[0-9]+";
      default = "0.0.0.0/0";
      description = "IPv4 source CIDR allowed to reach the SMB server; 0.0.0.0/0 allows every IPv4 source.";
    };
    readOnly = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Make the named SMB share read-only.";
    };
  };
  config = lib.mkMerge [
    {
      # WireGuard is native to NetworkManager. Overlay VPNs run their own daemons.
      environment.systemPackages =
        lib.optional cfg.vpn.wireguard pkgs.wireguard-tools
        ++ lib.optional cfg.vpn.tailscale pkgs.trayscale;
      services.tailscale = lib.mkIf cfg.vpn.tailscale {
        enable = true;
        useRoutingFeatures = "client";
        extraSetFlags = [ "--operator=${cfg.user.name}" ];
        openFirewall = true;
      };
      services.zerotierone = lib.mkIf cfg.vpn.zerotier {
        enable = true;
        joinNetworks = cfg.vpn.zerotierNetworks;
      };
      # Do not let NetworkManager compete with the overlay VPN daemons.
      networking.networkmanager.unmanaged =
        lib.optional cfg.vpn.tailscale "interface-name:tailscale0"
        ++ lib.optional cfg.vpn.zerotier "interface-name:zt*";
      assertions = [
        {
          assertion =
            cfg.sharing.network == "0.0.0.0/0" || (import ../lib/valid-ipv4-cidr.nix lib) cfg.sharing.network;
          message = "SMB access requires an IPv4 CIDR (/1 through /32), or 0.0.0.0/0 for every IPv4 source.";
        }
        {
          assertion =
            !(builtins.elem (lib.toLower cfg.sharing.folder) [
              "global"
              "homes"
              "printers"
            ]);
          message = "Choose a dedicated SMB folder name, not a reserved Samba section.";
        }
        {
          assertion = cfg.vpn.zerotier || cfg.vpn.zerotierNetworks == [ ];
          message = "ZeroTier network IDs require nix2office.vpn.zerotier = true.";
        }
      ];
    }
    (lib.mkIf (!server) {
      environment.etc."samba/smb.conf".text = ''
        [global]
        workgroup = ${cfg.sharing.workgroup}
        client min protocol = SMB2
      '';
    })
    (lib.mkIf server {
      services.samba = {
        enable = true;
        openFirewall = false;
        nmbd.enable = false;
        winbindd.enable = false;
        settings = {
          global = {
            workgroup = cfg.sharing.workgroup;
            security = "user";
            "map to guest" = "Never";
            "server min protocol" = "SMB2";
            "client min protocol" = "SMB2";
            "smb ports" = "445";
            "load printers" = "no";
            "disable spoolss" = "yes";
          };
          ${cfg.sharing.folder} = {
            path = sharePath;
            "valid users" = cfg.user.name;
            "guest ok" = "no";
            "read only" = if cfg.sharing.readOnly then "yes" else "no";
            "create mask" = "0600";
            "directory mask" = "0700";
          };
        };
      };
      networking.firewall.extraInputRules = ''
        ip saddr ${cfg.sharing.network} tcp dport 445 accept
      '';
      systemd.tmpfiles.rules = [ "d ${sharePath} 0700 ${cfg.user.name} users -" ];
    })
  ];
}

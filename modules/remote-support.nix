{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.nix2office.remoteSupport;
  python = pkgs.python3.withPackages (p: [ p.toml ]);
  settings = pkgs.writeText "rustdesk-settings.json" (
    builtins.toJSON {
      inherit (cfg) mode;
      id_server = cfg.idServer;
      relay_server = cfg.relayServer;
      public_key = cfg.publicKey;
    }
  );
  prepare = pkgs.writeShellScript "rustdesk-prepare" ''
    exec ${python}/bin/python ${../scripts/rustdesk-settings.py} ${settings} ${lib.escapeShellArg cfg.passwordFile}
  '';
in
{
  options.nix2office.remoteSupport = {
    mode = lib.mkOption {
      type = lib.types.enum [
        "off"
        "consent"
        "unattended"
      ];
      default = "off";
    };
    idServer = lib.mkOption {
      type = lib.types.str;
      default = "";
    };
    relayServer = lib.mkOption {
      type = lib.types.str;
      default = "";
    };
    publicKey = lib.mkOption {
      type = lib.types.str;
      default = "";
    };
    passwordFile = lib.mkOption {
      type = lib.types.str;
      default = "/run/secrets/rustdesk-password";
      description = "Runtime secret path; never a store file.";
    };
  };
  config = lib.mkIf (cfg.mode != "off") {
    assertions = [
      {
        assertion = cfg.idServer != "" && cfg.relayServer != "" && cfg.publicKey != "";
        message = "RustDesk needs hbbs, hbbr and a public server key.";
      }
      {
        assertion = !(lib.hasPrefix "/nix/store/" cfg.passwordFile);
        message = "RustDesk password must remain outside the Nix store.";
      }
    ];
    environment.systemPackages = [ pkgs.rustdesk-flutter ];
    home-manager.users.${config.nix2office.user.name}.systemd.user.services.nix2office-rustdesk = {
      Unit = {
        Description = "RustDesk office support (logged-in desktop)";
        After = [ "graphical-session.target" ];
        PartOf = [ "graphical-session.target" ];
      };
      Install.WantedBy = [ "graphical-session.target" ];
      Service = {
        ExecStartPre = "${prepare}";
        ExecStart = "${pkgs.rustdesk-flutter}/bin/rustdesk --tray";
        Restart = "on-failure";
        RestartSec = 10;
        UMask = "0077";
      };
    };
  };
}

{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.nix2office.remoteSupport;
  python = pkgs.python3.withPackages (p: [
    p.toml
    p.pynacl
  ]);
  settings = pkgs.writeText "rustdesk-settings.json" (
    builtins.toJSON {
      inherit (cfg) mode;
      id_server = cfg.idServer;
      relay_server = cfg.relayServer;
      public_key = cfg.publicKey;
    }
  );
  prepare = pkgs.writeShellScript "rustdesk-prepare" ''
    exec ${python}/bin/python ${../scripts/rustdesk-settings.py} --system \
      ${settings} /root/.config/rustdesk \
      ${if cfg.mode == "unattended" then ''"$CREDENTIALS_DIRECTORY/password"'' else "''"} \
      ${pkgs.rustdesk-flutter}/bin/rustdesk ${lib.escapeShellArg config.nix2office.user.name} lightdm
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
        assertion = lib.hasPrefix "/" cfg.passwordFile && !(lib.hasPrefix "/nix/store/" cfg.passwordFile);
        message = "RustDesk password must remain outside the Nix store.";
      }
      {
        assertion = config.services.xserver.enable && config.services.xserver.displayManager.lightdm.enable;
        message = "RustDesk pre-login support requires the office LightDM/Xorg desktop.";
      }
    ];
    environment.systemPackages = [ pkgs.rustdesk-flutter ];
    # RustDesk 1.4.5's X11 fallback uses the active account's ~/.Xauthority.
    # Keep LightDM's cookie authentication, including for its greeter account.
    services.xserver.displayManager.lightdm.extraConfig = "user-authority-in-system-dir=false";
    systemd.services.rustdesk = {
      description = "RustDesk office support (LightDM and desktop)";
      wantedBy = [ "multi-user.target" ];
      wants = [
        "network-online.target"
        "display-manager.service"
      ];
      after = [
        "network-online.target"
        "display-manager.service"
        "systemd-user-sessions.service"
        "sops-install-secrets.service"
      ];
      path = with pkgs; [
        bash
        coreutils
        gawk
        gnugrep
        gnused
        procps
        getent
        systemd
        util-linux
        sudo
        xrandr
      ];
      environment.HOME = "/root";
      # Do not set XDG_CONFIG_HOME: sudo -E must let each server use its own HOME.
      serviceConfig = {
        Type = "simple";
        User = "root";
        ExecStartPre = prepare;
        ExecStart = "${pkgs.rustdesk-flutter}/bin/rustdesk --service";
        LoadCredential = lib.optional (cfg.mode == "unattended") "password:${cfg.passwordFile}";
        Restart = "on-failure";
        RestartSec = 10;
        UMask = "0077";
        UnsetEnvironment = [ "XDG_CONFIG_HOME" ];
        KillMode = "control-group";
        TimeoutStopSec = 30;
        LimitNOFILE = 100000;
      };
    };
    # --service owns --server and its tray; do not race it with a user daemon.
  };
}

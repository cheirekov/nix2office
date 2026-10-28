{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.nix2office;
  libreofficeBg = import ../packages/libreoffice-bg.nix { inherit pkgs; };
in
{
  options.nix2office = {
    bootSplash.enable = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = "Show a Plymouth spinner instead of verbose boot messages.";
    };
    adminAuthorizedKeys = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [ ];
      description = "Public SSH keys allowed to log in as admin.";
    };
    adminNetwork = lib.mkOption {
      type = lib.types.str;
      default = "192.0.2.0/24";
      description = "Trusted IPv4 CIDR for administrative SSH. Set this in the deployment.";
    };
    officePasswordFile = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      description = "Runtime path to the office password hash, normally a sops secret.";
    };
    adminPasswordFile = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      description = "Runtime path to the admin password hash, normally a sops secret.";
    };
  };

  config = {
    system.stateVersion = lib.mkDefault "26.05";
    boot.plymouth = {
      enable = cfg.bootSplash.enable;
      theme = lib.mkDefault "spinner";
    };
    boot.kernelParams = lib.optionals cfg.bootSplash.enable [
      "quiet"
      "udev.log_level=3"
    ];
    boot.consoleLogLevel = lib.mkIf cfg.bootSplash.enable 3;
    boot.initrd.verbose = lib.mkIf cfg.bootSplash.enable false;
    nix.settings.experimental-features = [
      "nix-command"
      "flakes"
    ];
    nix.settings.substituters = [ "https://cache.nixos.org/" ];
    nix.settings.auto-optimise-store = true;
    system.autoUpgrade.enable = false;

    time.timeZone = "Europe/Sofia";
    i18n.defaultLocale = "bg_BG.UTF-8";
    i18n.supportedLocales = [
      "bg_BG.UTF-8/UTF-8"
      "en_US.UTF-8/UTF-8"
    ];
    console.useXkbConfig = true;
    services.xserver = {
      enable = true;
      xkb = {
        layout = "us,bg";
        variant = ",phonetic";
        options = "grp:alt_shift_toggle";
      };
      desktopManager.xfce.enable = true;
      displayManager.lightdm.enable = true;
      displayManager.lightdm.greeters.gtk.indicators = [
        "~host"
        "~spacer"
        "~clock"
        "~spacer"
        "~layout"
        "~session"
        "~a11y"
        "~power"
      ];
      # LightDM's fallback uses a tab before variants; libxklavier uses an underscore.
      displayManager.lightdm.greeters.gtk.extraConfig = "keyboard-layouts=us;bg\tphonetic;bg_phonetic";
      # The greeter may replace the server keymap when a password layout is selected.
      displayManager.sessionCommands = ''
        ${lib.getExe pkgs.setxkbmap} \
          -layout ${lib.escapeShellArg config.services.xserver.xkb.layout} \
          -variant ${lib.escapeShellArg config.services.xserver.xkb.variant} \
          -option ${lib.escapeShellArg config.services.xserver.xkb.options}
      '';
      excludePackages = [ pkgs.xterm ];
    };
    services.displayManager.defaultSession = "xfce";
    services.libinput.enable = true;
    programs.xfconf.enable = true;
    hardware.graphics.enable = true;
    hardware.cpu.intel.updateMicrocode = lib.mkDefault true;
    hardware.enableRedistributableFirmware = true;
    security.rtkit.enable = true;
    services.pipewire = {
      enable = true;
      alsa.enable = true;
      pulse.enable = true;
    };
    services.gnome.gnome-keyring.enable = true;
    security.pam.services.lightdm.enableGnomeKeyring = true;

    networking.networkmanager.enable = true;
    networking.nftables.enable = true;
    networking.firewall = {
      enable = true;
      extraInputRules = lib.mkIf (cfg.adminAuthorizedKeys != [ ]) ''
        ip saddr ${cfg.adminNetwork} tcp dport 22 accept
      '';
    };
    services.openssh = {
      enable = cfg.adminAuthorizedKeys != [ ];
      openFirewall = false;
      settings = {
        PasswordAuthentication = false;
        KbdInteractiveAuthentication = false;
        PermitRootLogin = "no";
        AllowUsers = [ "admin" ];
        AllowAgentForwarding = false;
        X11Forwarding = false;
      };
    };

    users.mutableUsers = false;
    users.users = {
      root.hashedPassword = "!";
      office = {
        isNormalUser = true;
        description = "Офис";
        extraGroups = [
          "networkmanager"
          "scanner"
          "lp"
        ];
      }
      // (
        if cfg.officePasswordFile == null then
          { hashedPassword = "!"; }
        else
          {
            hashedPasswordFile = cfg.officePasswordFile;
          }
      );
      admin = {
        isNormalUser = true;
        description = "Администратор";
        extraGroups = [
          "wheel"
          "networkmanager"
        ];
        openssh.authorizedKeys.keys = cfg.adminAuthorizedKeys;
      }
      // (
        if cfg.adminPasswordFile == null then
          { hashedPassword = "!"; }
        else
          {
            hashedPasswordFile = cfg.adminPasswordFile;
          }
      );
    };
    security.sudo.wheelNeedsPassword = true;

    services.printing = {
      enable = true;
      browsing = true;
      defaultShared = false;
    };
    services.avahi = {
      enable = true;
      nssmdns4 = true;
      openFirewall = true;
    };
    hardware.sane = {
      enable = true;
      extraBackends = [ pkgs.sane-airscan ];
    };
    services.saned.enable = false;
    services.udisks2.enable = true;
    services.gvfs.enable = true;
    services.tumbler.enable = true;
    services.fstrim.enable = true;
    programs.firefox = {
      enable = true;
      package = pkgs.firefox-esr;
      languagePacks = [ "bg" ];
      preferences."intl.locale.requested" = "bg";
      preferencesStatus = "default";
    };
    zramSwap = {
      enable = true;
      memoryPercent = 50;
      priority = 100;
    };
    boot.kernel.sysctl."vm.swappiness" = 60;

    fonts.packages = with pkgs; [
      liberation_ttf
      dejavu_fonts
      noto-fonts
      noto-fonts-color-emoji
    ];
    environment.systemPackages = with pkgs; [
      libreofficeBg
      atril
      simple-scan
      nextcloud-client
      pavucontrol
      xfce4-whiskermenu-plugin
      xfce4-xkb-plugin
      thunar-archive-plugin
      xarchiver
      hunspell
      hunspellDicts.en_US
      htop
      nano
    ];
    home-manager = {
      useGlobalPkgs = true;
      useUserPackages = true;
      users.office = import ../home/office.nix;
    };
  };
}

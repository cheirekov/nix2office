{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.nix2office;
  applications = import ../lib/applications.nix {
    inherit pkgs;
    inherit (cfg) apps;
  };
  bulgarianVariant = if cfg.keyboard.bulgarian == "bds" then "" else "phonetic";
in
{
  imports = [ ./networking.nix ];
  options.nix2office = (import ../lib/desktop-options.nix { inherit lib; }) // {
    devices.bluetooth = lib.mkEnableOption "Bluetooth and the Blueman desktop controls";
    devices.unfreeFirmware = lib.mkEnableOption "additional unfree firmware (explicit opt-in)";
    performance.cpuGovernor = lib.mkOption {
      type = lib.types.enum [
        "auto"
        "schedutil"
        "ondemand"
        "powersave"
        "performance"
      ];
      default = "auto";
      description = "CPU frequency governor; auto leaves the kernel default. The assistant recommends from the target's available governors.";
    };
    hardware.cpuVendor = lib.mkOption {
      type = lib.types.enum [
        "intel"
        "amd"
        "unknown"
      ];
      default = "intel";
      description = "CPU vendor for microcode; the assistant detects it on the target.";
    };
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
      type = lib.types.strMatching "[0-9.]+/[0-9]+";
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
    assertions = [
      {
        assertion = (import ../lib/valid-ipv4-cidr.nix lib) cfg.adminNetwork;
        message = "Administrative access requires a specific IPv4 CIDR with prefix 1 through 32.";
      }
      {
        assertion =
          !(builtins.elem cfg.user.name [
            "root"
            "admin"
            "nobody"
            "lightdm"
            "nixos"
          ]);
        message = "Choose a separate desktop login name, not a reserved or administrator account.";
      }
      {
        assertion = builtins.match "[^:\n\r,]*" cfg.user.fullName != null;
        message = "The displayed full name must not contain colons, commas or line breaks (GECOS separators).";
      }
    ];
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
        variant = ",${bulgarianVariant}";
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
      displayManager.lightdm.greeters.gtk.extraConfig =
        if bulgarianVariant == "" then
          "keyboard-layouts=us;bg"
        else
          "keyboard-layouts=us;bg\t${bulgarianVariant};bg_${bulgarianVariant}";
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
    hardware.cpu.intel.updateMicrocode = lib.mkDefault (cfg.hardware.cpuVendor == "intel");
    hardware.cpu.amd.updateMicrocode = lib.mkDefault (cfg.hardware.cpuVendor == "amd");
    powerManagement.cpuFreqGovernor = lib.mkIf (
      cfg.performance.cpuGovernor != "auto"
    ) cfg.performance.cpuGovernor;
    hardware.enableRedistributableFirmware = true;
    hardware.enableAllFirmware = cfg.devices.unfreeFirmware;
    hardware.bluetooth.enable = cfg.devices.bluetooth;
    hardware.bluetooth.powerOnBoot = cfg.devices.bluetooth;
    services.blueman.enable = cfg.devices.bluetooth;
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
      ${cfg.user.name} = {
        isNormalUser = true;
        description = cfg.user.fullName;
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
      enable = cfg.apps.browser == "firefox-esr";
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
    # Allow only the explicitly selected proprietary browser, not every unfree package.
    nixpkgs.config.allowUnfreePredicate =
      pkg:
      lib.getName pkg == "google-chrome"
      || (
        cfg.devices.unfreeFirmware
        && builtins.elem (lib.getName pkg) [
          "broadcom-bt-firmware"
          "b43-firmware"
          "b43-firmware-cutter"
          "xone-dongle-firmware"
          "facetimehd-calibration"
          "facetimehd-firmware"
        ]
      );
    environment.systemPackages =
      (with pkgs; [
        atril
        simple-scan
        pavucontrol
        xfce4-whiskermenu-plugin
        xfce4-xkb-plugin
        thunar-archive-plugin
        xarchiver
        hunspell
        hunspellDicts.en_US
        htop
        nano
      ])
      ++ applications.artcraftPackages
      ++ applications.officePackages
      ++ applications.pdfPackages
      ++ lib.optional (cfg.apps.browser != "firefox-esr") applications.browser.package
      ++ lib.optional cfg.apps.nextcloud pkgs.nextcloud-client;
    home-manager = {
      useGlobalPkgs = true;
      useUserPackages = true;
      users.${cfg.user.name} = {
        imports = [ ../home/office.nix ];
        nix2office = {
          inherit (cfg)
            user
            apps
            keyboard
            vpn
            ;
        };
      };
    };
  };
}

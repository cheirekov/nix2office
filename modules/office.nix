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
    vaapi = cfg.performance.vaapi;
  };
  bulgarianVariant = if cfg.keyboard.bulgarian == "bds" then "" else "phonetic";
  officeEnabled = cfg.role != "thin";
  # Firefox content processes: scale with CPU threads but cap by RAM so a weak
  # machine never spawns more processes than it can keep resident. 0 = unknown.
  processCount =
    let
      byRam =
        if cfg.hardware.memoryMiB > 0 && cfg.hardware.memoryMiB < 2048 then
          2
        else if cfg.hardware.memoryMiB > 0 && cfg.hardware.memoryMiB < 4096 then
          4
        else if cfg.hardware.memoryMiB > 0 && cfg.hardware.memoryMiB < 8192 then
          6
        else
          8;
      byCores = if cfg.hardware.threads > 0 then lib.min cfg.hardware.threads 8 else 8;
    in
    lib.min byRam byCores;
in
{
  imports = [
    ./networking.nix
    ./remote-support.nix
    ./thin-client.nix
  ];
  options.nix2office = (import ../lib/desktop-options.nix { inherit lib; }) // {
    fonts.microsoftCore = lib.mkEnableOption "Microsoft core fonts (unfreeRedistributable)";
    fonts.officeFallbacks = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = "Carlito and Caladea office font fallbacks.";
    };
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
    performance.vaapi = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = "VA-API hardware video decoding, offloading H.264 from the CPU on supported Intel/AMD GPUs.";
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
    hardware.gpuDriver = lib.mkOption {
      type = lib.types.enum [
        "i915"
        "xe"
        "amdgpu"
        "radeon"
        "nouveau"
        "unknown"
      ];
      default = "unknown";
      description = "Detected early graphics driver; selects the VA-API decode driver.";
    };
    hardware.memoryMiB = lib.mkOption {
      type = lib.types.ints.unsigned;
      default = 0;
      description = "Detected usable RAM in MiB; 0 means unknown. Drives adaptive Firefox memory tuning.";
    };
    hardware.threads = lib.mkOption {
      type = lib.types.ints.unsigned;
      default = 0;
      description = "Detected online CPU threads; 0 means unknown. Drives the Firefox content-process count.";
    };
    role = lib.mkOption {
      type = lib.types.enum [
        "office"
        "hybrid"
        "thin"
      ];
      default = "office";
      description = "Machine role: full office, office plus RDP thin client, or thin client only.";
    };
    thinClient = {
      credentials = lib.mkOption {
        type = lib.types.enum [
          "interactive"
          "sops"
        ];
        default = "interactive";
        description = "RDP password source: prompt at connection, or a sops secret.";
      };
      redirect = lib.mkOption {
        type = lib.types.listOf (
          lib.types.enum [
            "smartcard"
            "clipboard"
            "audio"
            "drives"
            "usb"
          ]
        );
        default = [
          "smartcard"
          "clipboard"
          "audio"
          "drives"
          "usb"
        ];
        description = "Device redirection enabled for RDP sessions.";
      };
      profiles = lib.mkOption {
        type = lib.types.listOf (
          lib.types.submodule (
            { ... }: {
              options = {
                name = lib.mkOption { type = lib.types.str; };
                host = lib.mkOption { type = lib.types.str; };
                user = lib.mkOption { type = lib.types.str; };
                port = lib.mkOption {
                  type = lib.types.port;
                  default = 3389;
                };
                remoteApps = lib.mkOption {
                  type = lib.types.listOf lib.types.str;
                  default = [ ];
                };
              };
            }
          )
        );
        default = [ ];
        description = "RDP profiles; each can publish RemoteApp aliases.";
      };
      fullscreen = lib.mkOption {
        type = lib.types.bool;
        default = false;
        description = "Start RDP sessions in fullscreen mode.";
      };
      passwordFile = lib.mkOption {
        type = lib.types.str;
        default = "/run/secrets/rdp-password";
        description = "Runtime path to the decrypted RDP password; never a store file.";
      };
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
      default = "0.0.0.0/0";
      description = "IPv4 source CIDR for administrative SSH; 0.0.0.0/0 allows every IPv4 source.";
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
        assertion =
          cfg.adminNetwork == "0.0.0.0/0" || (import ../lib/valid-ipv4-cidr.nix lib) cfg.adminNetwork;
        message = "Administrative SSH requires an IPv4 CIDR (/1 through /32), or 0.0.0.0/0 for every IPv4 source.";
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
    # The light office profile omits local man/info/NixOS manuals to keep a
    # small SSD lean; re-enable these options in a host override when needed.
    documentation.nixos.enable = false;
    documentation.doc.enable = false;
    documentation.man.enable = false;
    documentation.info.enable = false;

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
      desktopManager.xfce.enable = officeEnabled;
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
    services.displayManager.defaultSession = if officeEnabled then "xfce" else "none+openbox";
    services.libinput.enable = true;
    programs.xfconf.enable = officeEnabled;
    hardware.graphics.enable = true;
    hardware.graphics.extraPackages = lib.optionals cfg.performance.vaapi (
      if cfg.hardware.gpuDriver == "i915" then
        [ pkgs.intel-vaapi-driver ]
      else if cfg.hardware.gpuDriver == "xe" then
        [ pkgs.intel-media-driver ]
      else if cfg.hardware.gpuDriver == "amdgpu" || cfg.hardware.gpuDriver == "radeon" then
        [ pkgs.mesa ]
      else if cfg.hardware.gpuDriver == "nouveau" then
        [ pkgs.libva-vdpau-driver ]
      else
        [ ]
    );
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
      enable = officeEnabled && cfg.apps.browser == "firefox-esr";
      package = pkgs.firefox-esr;
      languagePacks = [ "bg" ];
      preferences = {
        "intl.locale.requested" = "bg";
        "dom.ipc.processCount" = processCount;
        "browser.tabs.unloadOnLowMemory" = true;
      }
      // lib.optionalAttrs cfg.performance.vaapi {
        "media.ffmpeg.vaapi.enabled" = true;
        "media.hardware-video-decoding.enabled" = true;
        "gfx.webrender.all" = true;
        "media.webm.enabled" = false;
        "media.av1.enabled" = false;
      };
      preferencesStatus = "default";
      policies = {
        ExtensionSettings = {
          "uBlock0@raymondhill.net" = {
            installation_mode = "force_installed";
            install_url = "https://addons.mozilla.org/firefox/downloads/latest/ublock-origin/latest.xpi";
          };
        };
      };
    };
    zramSwap = {
      enable = true;
      memoryPercent = 100;
      priority = 100;
    };
    boot.kernel.sysctl."vm.swappiness" = 60;

    fonts.packages =
      with pkgs;
      [
        liberation_ttf
        dejavu_fonts
        noto-fonts
        noto-fonts-color-emoji
      ]
      ++ lib.optionals officeEnabled (
        (lib.optionals cfg.fonts.officeFallbacks [
          pkgs.carlito
          pkgs.caladea
        ])
        ++ lib.optional cfg.fonts.microsoftCore pkgs.corefonts
      );
    # Allow only the explicitly selected proprietary browser, not every unfree package.
    nixpkgs.config.allowUnfreePredicate =
      pkg:
      lib.getName pkg == "google-chrome"
      || (cfg.fonts.microsoftCore && lib.getName pkg == "corefonts")
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
        pavucontrol
        htop
        nano
      ])
      ++ (
        with pkgs;
        lib.optionals officeEnabled [
          atril
          simple-scan
          xfce4-whiskermenu-plugin
          xfce4-xkb-plugin
          thunar-archive-plugin
          xarchiver
          hunspell
          hunspellDicts.en_US
        ]
      )
      ++ [ (import ../packages/diagnose.nix { inherit pkgs; }) ]
      ++ lib.optionals officeEnabled (
        applications.extraPackages
        ++ applications.artcraftPackages
        ++ applications.officePackages
        ++ applications.pdfPackages
        ++ lib.optional (cfg.apps.browser != "firefox-esr") applications.browser.package
        ++ lib.optional cfg.apps.nextcloud pkgs.nextcloud-client
      );
    home-manager = {
      useGlobalPkgs = true;
      useUserPackages = true;
      users.${cfg.user.name} = {
        imports = [
          (if officeEnabled then ../home/office.nix else ../home/thin.nix)
        ];
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

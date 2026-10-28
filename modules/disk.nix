{ config, lib, ... }:
let
  cfg = config.nix2office;
  bios = cfg.bootMode == "bios";
in
{
  options.nix2office = {
    diskDevice = lib.mkOption {
      type = lib.types.strMatching "/dev/disk/by-id/[A-Za-z0-9_.:+-]+";
      example = "/dev/disk/by-id/ata-YOUR_INTERNAL_SSD";
      description = "Persistent whole-disk ID. Installation erases that disk.";
    };
    bootMode = lib.mkOption {
      type = lib.types.enum [
        "bios"
        "uefi"
      ];
      default = "bios";
      description = "Boot mode of both the rescue system and installed machine.";
    };
  };
  config = {
    assertions = [
      {
        assertion = builtins.match ".*-part[0-9]+" cfg.diskDevice == null;
        message = "Select a whole internal disk, not a by-id partition.";
      }
    ];
    boot.loader.grub = lib.mkIf bios {
      enable = true;
      efiSupport = false;
    };
    boot.loader.systemd-boot.enable = !bios;
    boot.loader.efi.canTouchEfiVariables = !bios;
    boot.initrd.availableKernelModules = [
      "ahci"
      "nvme"
      "xhci_pci"
      "ehci_pci"
      "usb_storage"
      "usbhid"
      "sd_mod"
      "virtio_pci"
      "virtio_blk"
    ];
    disko.devices.disk.system = {
      type = "disk";
      device = cfg.diskDevice;
      content = {
        type = "gpt";
        partitions =
          (
            if bios then
              {
                bios = {
                  size = "1M";
                  type = "EF02";
                };
              }
            else
              {
                ESP = {
                  size = "512M";
                  type = "EF00";
                  content = {
                    type = "filesystem";
                    format = "vfat";
                    mountpoint = "/boot";
                    mountOptions = [ "umask=0077" ];
                  };
                };
              }
          )
          // {
            swap = {
              size = "4G";
              content = {
                type = "swap";
                priority = 10;
              };
            };
            root = {
              size = "100%";
              content = {
                type = "filesystem";
                format = "ext4";
                mountpoint = "/";
                mountOptions = [ "noatime" ];
              };
            };
          };
      };
    };
  };
}

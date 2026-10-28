{ config, lib, ... }:
{
  options.nix2office.diskDevice = lib.mkOption {
    type = lib.types.str;
    example = "/dev/disk/by-id/ata-YOUR_INTERNAL_SSD";
    description = "Whole installation disk by persistent ID. Formatting destroys its contents.";
  };
  config = {
    assertions = [
      {
        assertion = lib.hasPrefix "/dev/disk/by-id/" config.nix2office.diskDevice;
        message = "nix2office.diskDevice must select a persistent whole-disk by-id path.";
      }
    ];
    boot.loader.grub = {
      enable = true;
      efiSupport = false;
    };
    boot.initrd.availableKernelModules = [
      "ahci"
      "xhci_pci"
      "usb_storage"
      "sd_mod"
    ];
    disko.devices.disk.system = {
      type = "disk";
      device = config.nix2office.diskDevice;
      content = {
        type = "gpt";
        partitions = {
          bios = {
            size = "1M";
            type = "EF02";
          };
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

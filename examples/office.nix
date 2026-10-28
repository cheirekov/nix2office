{
  networking.hostName = "office-example";
  nix2office.diskDevice = "/dev/disk/by-id/REPLACE_WITH_INTERNAL_DISK";
  users.allowNoPasswordLogin = true; # An intentionally locked, non-installable example.
  # Both accounts are locked until the private deployment supplies password files.
  # SSH remains disabled until adminAuthorizedKeys is populated.
}

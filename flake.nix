{
  description = "A lightweight Bulgarian NixOS office desktop with a familiar layout";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-26.05";
    home-manager = {
      url = "github:nix-community/home-manager/release-26.05";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    disko = {
      url = "github:nix-community/disko";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    sops-nix = {
      url = "github:Mic92/sops-nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs =
    inputs@{ self, nixpkgs, ... }:
    {
      nixosModules = {
        default = self.nixosModules.office;
        office = {
          imports = [
            inputs.home-manager.nixosModules.home-manager
            inputs.sops-nix.nixosModules.sops
            ./modules/office.nix
          ];
        };
        legacy-bios = {
          imports = [
            inputs.disko.nixosModules.disko
            ./modules/legacy-bios.nix
          ];
        };
      };
      homeManagerModules.office = import ./home/office.nix;
      nixosConfigurations.office-example = nixpkgs.lib.nixosSystem {
        system = "x86_64-linux";
        modules = [
          self.nixosModules.office
          self.nixosModules.legacy-bios
          ./examples/office.nix
        ];
      };
      formatter.x86_64-linux = nixpkgs.legacyPackages.x86_64-linux.nixfmt;
      devShells.x86_64-linux.default =
        let
          pkgs = nixpkgs.legacyPackages.x86_64-linux;
        in
        pkgs.mkShellNoCC {
          packages = with pkgs; [
            age
            sops
            mkpasswd
            nixfmt
          ];
        };
    };
}

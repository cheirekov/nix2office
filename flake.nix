{
  description = "A lightweight Bulgarian NixOS office desktop with a familiar layout";

  inputs = {
    nix-index-database.url = "github:nix-community/nix-index-database";
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
            (import ./modules/comma.nix inputs.nix-index-database)
            ./modules/office.nix
          ];
        };
        legacy-bios = {
          imports = [
            inputs.disko.nixosModules.disko
            ./modules/legacy-bios.nix
          ];
        };
        disk = {
          imports = [
            inputs.disko.nixosModules.disko
            ./modules/disk.nix
          ];
        };
      };
      lib.machineModule = file: import ./modules/machine.nix file;
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
      packages.x86_64-linux.configure =
        let
          pkgs = nixpkgs.legacyPackages.x86_64-linux;
          python = pkgs.python3.withPackages (p: [ p.questionary ]);
        in
        pkgs.writeShellApplication {
          name = "nix2office-configure";
          runtimeInputs = with pkgs; [
            python
            age
            sops
            mkpasswd
            git
            openssh
            util-linux
            coreutils
            gawk
            gnused
            gzip
            nix
          ];
          text = ''
            export NIX2OFFICE_SOURCE=${
              nixpkgs.lib.escapeShellArg (if self ? rev then "github:cheirekov/nix2office/${self.rev}" else "")
            }
            exec ${python}/bin/python ${./scripts}/configure.py "$@"
          '';
        };
      packages.x86_64-linux.maintain =
        let
          pkgs = nixpkgs.legacyPackages.x86_64-linux;
          python = pkgs.python3.withPackages (p: [ p.questionary ]);
        in
        pkgs.writeShellApplication {
          name = "nix2office-maintain";
          runtimeInputs = [
            python
            pkgs.nix
            pkgs.git
            pkgs.openssh
            pkgs.gzip
            pkgs.age
            pkgs.sops
            pkgs.coreutils
          ];
          text = ''
            export NIX2OFFICE_SOURCE=${
              nixpkgs.lib.escapeShellArg (if self ? rev then "github:cheirekov/nix2office/${self.rev}" else "")
            }
            exec ${python}/bin/python ${./scripts}/maintain.py "$@"
          '';
        };
      apps.x86_64-linux.maintain = {
        type = "app";
        program = "${self.packages.x86_64-linux.maintain}/bin/nix2office-maintain";
      };
      packages.x86_64-linux.comma = import ./packages/comma.nix {
        pkgs = nixpkgs.legacyPackages.x86_64-linux;
        database = inputs.nix-index-database;
      };
      apps.x86_64-linux.comma = {
        type = "app";
        program = "${self.packages.x86_64-linux.comma}/bin/comma";
      };
      packages.x86_64-linux.artcraft = nixpkgs.legacyPackages.x86_64-linux.symlinkJoin {
        name = "artcraft-office-experimental";
        paths = builtins.attrValues (
          import ./packages/artcraft.nix { pkgs = nixpkgs.legacyPackages.x86_64-linux; }
        );
      };
      packages.x86_64-linux.install =
        let
          pkgs = nixpkgs.legacyPackages.x86_64-linux;
        in
        pkgs.writeShellApplication {
          name = "nix2office-install";
          text = ''
            exec ${self.packages.x86_64-linux.configure}/bin/nix2office-configure --rescue "$@"
          '';
        };
      apps.x86_64-linux.install = {
        type = "app";
        program = "${self.packages.x86_64-linux.install}/bin/nix2office-install";
      };
      apps.x86_64-linux.configure = {
        type = "app";
        program = "${self.packages.x86_64-linux.configure}/bin/nix2office-configure";
      };
      apps.x86_64-linux.default = self.apps.x86_64-linux.configure;
      devShells.x86_64-linux.default =
        let
          pkgs = nixpkgs.legacyPackages.x86_64-linux;
        in
        pkgs.mkShellNoCC {
          packages = with pkgs; [
            (python3.withPackages (p: [
              p.questionary
              p.toml
            ]))
            age
            sops
            mkpasswd
            nixfmt
          ];
        };
    };
}

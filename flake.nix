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
    let
      pkgs = nixpkgs.legacyPackages.x86_64-linux;
      developmentPython = pkgs.python3.withPackages (p: [
        p.questionary
        p.toml
        p.pynacl
      ]);
      developmentTools = with pkgs; [
        developmentPython
        age
        sops
        mkpasswd
        nixfmt
        deadnix
        nurl
        git
        openssh
      ];
    in
    {
      checks.x86_64-linux = {
        python-tests =
          pkgs.runCommand "nix2office-python-tests"
            {
              nativeBuildInputs = developmentTools;
            }
            ''
                    export HOME="$TMPDIR/home"
              export NIX2OFFICE_REMOTE_SUPPORT_EVALUATION=${
                pkgs.writeText "remote-support-evaluation.json" (
                  # Only evaluation facts, not runtime dependencies: do not build RustDesk.
                  builtins.unsafeDiscardStringContext (
                    builtins.toJSON (import ./tests/remote-support.nix { flake = self; })
                  )
                )
              }
                    mkdir -p "$HOME"
                    cp -r ${self} source
                    chmod -R u+w source
                    cd source
                  # The source filter excludes .git; the deployment-boundary test
                  # deliberately needs a checkout, recreated without private data.
                  git init -q
                    python3 -m unittest discover -s tests -v
                    touch "$out"
            '';
        nixos-eval = builtins.deepSeq (import ./tests/evaluate.nix {
          root = self.outPath;
          flake = self;
        }) (pkgs.runCommand "nix2office-nixos-eval" { } ''touch "$out"'');
        formatting =
          pkgs.runCommand "nix2office-formatting"
            {
              nativeBuildInputs = [ pkgs.nixfmt ];
            }
            ''
              cd ${self}
              nixfmt --check flake.nix modules/*.nix home/*.nix lib/*.nix packages/*.nix examples/*.nix
              touch "$out"
            '';
        deadnix =
          pkgs.runCommand "nix2office-deadnix"
            {
              nativeBuildInputs = [ pkgs.deadnix ];
            }
            ''
              deadnix --fail ${self}
              touch "$out"
            '';
      };
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
        meta.description = "Административна поддръжка на Nix2office";
        type = "app";
        program = "${self.packages.x86_64-linux.maintain}/bin/nix2office-maintain";
      };
      packages.x86_64-linux.comma = import ./packages/comma.nix {
        pkgs = nixpkgs.legacyPackages.x86_64-linux;
        database = inputs.nix-index-database;
      };
      apps.x86_64-linux.comma = {
        meta.description = "Временни програми с готов малък индекс";
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
        meta.description = "Инсталация през проверена nixos-rescue връзка";
        type = "app";
        program = "${self.packages.x86_64-linux.install}/bin/nix2office-install";
      };
      apps.x86_64-linux.configure = {
        meta.description = "Интерактивна подготовка на машинна конфигурация";
        type = "app";
        program = "${self.packages.x86_64-linux.configure}/bin/nix2office-configure";
      };
      apps.x86_64-linux.default = self.apps.x86_64-linux.configure;
      devShells.x86_64-linux.default =
        let
          pkgs = nixpkgs.legacyPackages.x86_64-linux;
        in
        pkgs.mkShellNoCC {
          packages = developmentTools;
        };
    };
}

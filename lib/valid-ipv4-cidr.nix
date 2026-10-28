lib: value:
let
  parts = builtins.match "([0-9]{1,3})\\.([0-9]{1,3})\\.([0-9]{1,3})\\.([0-9]{1,3})/([0-9]{1,2})" value;
  # fromJSON rejects leading zeros; reject them before converting.
  decimal = s: s == "0" || builtins.match "[1-9][0-9]*" s != null;
in
parts != null
&& lib.all decimal parts
&& lib.all (s: builtins.fromJSON s <= 255) (lib.take 4 parts)
&& builtins.fromJSON (builtins.elemAt parts 4) >= 1
&& builtins.fromJSON (builtins.elemAt parts 4) <= 32

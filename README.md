# SCDevice

Umbrella repository for local SCDevice work built on top of `KQCircuits`.

## Layout

- `KQCircuits/`: upstream-derived code tracked as a git submodule
- `scdevice_pcells/`: SCDevice-specific external PCells loaded through `KQC_EXTRA_SRC_PATHS`

## Setup

Initialize the submodule and expose the external PCell package before running KQCircuits tooling:

```bash
git submodule update --init --recursive
export KQC_EXTRA_SRC_PATHS="$PWD/scdevice_pcells"
```

With that environment variable set, `KQCircuits/util/create_element_from_path.py` accepts:

- built-in relative paths such as `kqcircuits/chips/demo.py`
- external relative paths such as `scdevice_pcells/chips/sqnl_launchers.py`
- absolute paths under either registered source root

## Git Workflow

`KQCircuits` should use a fork-based remote layout:

```bash
git -C KQCircuits remote -v
```

- `origin`: your fork of `KQCircuits`
- `upstream`: `iqm-finland/KQCircuits`

Typical update flow:

```bash
git -C KQCircuits fetch upstream
git -C KQCircuits switch yalgaeahn/local-work
git -C KQCircuits merge upstream/main
git add KQCircuits
```

User PCell changes should stay in `scdevice_pcells/` so upstream KQCircuits updates do not overwrite them.

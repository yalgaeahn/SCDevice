# SCDevice

Umbrella repository for local SCDevice work built on top of `KQCircuits`.

## Layout

- `KQCircuits/`: upstream-derived code tracked as a git submodule
- `scdevice_pcells/`: SCDevice-specific external PCells auto-detected in the standard layout

## Setup

Initialize the submodule before running KQCircuits tooling:

```bash
git submodule update --init --recursive
```

In the standard `SCDevice/KQCircuits` layout, `scdevice_pcells/` is auto-detected. `KQC_EXTRA_SRC_PATHS` is only needed for additional non-standard external packages.

With that default layout, `KQCircuits/util/create_element_from_path.py` accepts:

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

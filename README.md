# SCDevice

Umbrella repository for local SCDevice work built on top of `KQCircuits`.

## Repository Model

This repository intentionally uses a submodule layout:

- `SCDevice/`: the umbrella repo you clone, open in VSCode, and push for project-level work
- `KQCircuits/`: an upstream-derived Git submodule with its own history, remotes, branches, and push target
- `scdevice_pcells/`: SCDevice-specific chip and qubit code that stays outside upstream `KQCircuits`

This is not an accidental "Git repo inside another Git repo" setup. The goal is:

- keep local SCDevice code separate from upstream framework code
- track exactly which `KQCircuits` commit this project depends on
- let `KQCircuits` keep following upstream without overwriting `scdevice_pcells/`

The practical consequence is that `KQCircuits` and `SCDevice` are committed separately. If you change submodule code, commit and push `KQCircuits` first. Then go back to `SCDevice`, record the updated submodule pointer, and commit and push `SCDevice`.

## Layout

- `KQCircuits/`: upstream-derived framework code tracked as a Git submodule
- `scdevice_pcells/`: SCDevice-specific external code such as chips, qubits, and simulations auto-detected in the standard layout
- `util/create_element_from_path.py`: top-level compatibility wrapper used by the VSCode KLayout task

## Setup

These steps assume the standard `SCDevice/KQCircuits` layout and a local macOS setup. The Python package itself requires Python 3.11+.

### 1. Clone And Initialize

Run from the directory where you want the project checkout:

```bash
git clone git@github.com:yalgaeahn/SCDevice.git
cd SCDevice
git submodule update --init --recursive
```

If `KQCircuits/` looks empty or is missing expected files, the submodule initialization step was skipped.

### 2. Create The Python Environment

Run from `SCDevice/KQCircuits`:

```bash
cd KQCircuits
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip setuptools wheel
python -m pip install -e "klayout_package/python[dev,sim]"
```

Recommended working convention:

- open `SCDevice/` as the workspace root
- keep the active Python environment in `KQCircuits/.venv`
- install KQCircuits in editable mode from `KQCircuits/klayout_package/python`

### 3. Connect KQCircuits To KLayout

Run from `SCDevice/KQCircuits` with the virtual environment activated:

```bash
python setup_within_klayout.py
```

What this does:

- creates symlinks from the KLayout config directory to the local `KQCircuits` source tree
- queries the Python ABI used by the installed KLayout build
- installs GUI-side Python dependencies for that KLayout environment

Important notes:

- KLayout must already be installed before running this command.
- On macOS, the default executable path is `/Applications/klayout.app/Contents/MacOS/klayout`.
- If KLayout is installed elsewhere, update [.vscode/tasks.json](/Users/yalgaeahn/Research/20_Projects/SCDevice/.vscode/tasks.json) accordingly.
- `setup_within_klayout.py` uses `~/.klayout` by default, but may create an alternate config directory if another KQCircuits checkout is already linked there.
- If KLayout reports a system-protected `site-packages`, the setup falls back to `USER_SITE` for dependency installation.
- `.klayout-python.info` is a transient helper file created during KLayout environment detection and can be ignored.

## Current Code Work

Use the repository like this during development:

- edit `scdevice_pcells/` for project-specific chips, qubits, and simulations
- edit `KQCircuits/` only for upstream-derived framework changes or loader/tooling changes
- open `SCDevice/` as the workspace root so the VSCode task paths match the repository layout

For runnable simulation examples and the recommended small HFSS pilot flow, see [docs/simulation-examples.md](docs/simulation-examples.md).

### Simulation Export Temp Path

KQCircuits writes generated masks and simulation export outputs under `KQC_TMP_PATH`. If `KQC_TMP_PATH` is not set, KQCircuits falls back to the default `tmp` directory derived from its `ROOT_PATH`.

For this repository, the recommended local export base is:

```text
C:\Users\user\JSAHN\SCDevice\tmp
```

This keeps generated files outside the `KQCircuits` submodule and inside the top-level `SCDevice/tmp` directory, which is already ignored by git.

For a one-off PowerShell session:

```powershell
New-Item -ItemType Directory -Force "C:\Users\user\JSAHN\SCDevice\tmp"
$env:KQC_TMP_PATH = "C:\Users\user\JSAHN\SCDevice\tmp"
```

To persist the setting for future terminals and GUI tools:

```powershell
[Environment]::SetEnvironmentVariable("KQC_TMP_PATH", "C:\Users\user\JSAHN\SCDevice\tmp", "User")
```

After changing the persistent environment variable, restart VSCode, KLayout, Ansys, or any terminal that launches the export flow.

Editing `KQCircuits/klayout_package/python/kqcircuits/defaults.py` directly is the fastest local override, but it makes the `KQCircuits` submodule dirty and can create extra work when updating from upstream. Prefer `KQC_TMP_PATH` unless the default behavior needs to be changed for this checkout intentionally.

### `create_element_from_path` Usage

In the standard `SCDevice/KQCircuits` layout, `scdevice_pcells/` is auto-detected. You do not need `KQC_EXTRA_SRC_PATHS` for the built-in sibling package layout.

Accepted path formats include:

- `kqcircuits/...` built-in source paths such as `kqcircuits/chips/demo.py`
- `scdevice_pcells/...` external source paths such as `scdevice_pcells/chips/sqnl_launchers.py`
- absolute paths under either registered source root

The VSCode `Open in KLayout` task is defined relative to the `SCDevice` workspace root and calls the top-level wrapper at `util/create_element_from_path.py`. That wrapper forwards execution to `KQCircuits/util/create_element_from_path.py`, which keeps the task stable even though the real helper lives inside the submodule.

### Non-Standard External Packages

If you add external packages outside the standard sibling layout, register them explicitly:

```bash
export KQC_EXTRA_SRC_PATHS="/absolute/path/to/extra_package_root"
```

Use `KQC_EXTRA_SRC_PATHS` only for additional non-standard package roots. The standard sibling `scdevice_pcells/` package is auto-detected.

## Git Workflow

`KQCircuits` should use a fork-based remote layout:

```bash
git -C KQCircuits remote -v
```

Expected structure:

- `origin`: your fork of `KQCircuits`
- `upstream`: `https://github.com/iqm-finland/KQCircuits.git`

Typical upstream update flow:

```bash
git -C KQCircuits fetch upstream
git -C KQCircuits switch yalgaeahn/local-work
git -C KQCircuits merge upstream/main
git add KQCircuits
```

Typical local change flow when both repos are involved:

```bash
git -C KQCircuits status
git -C KQCircuits add <files>
git -C KQCircuits commit -m "Describe KQCircuits change"
git -C KQCircuits push -u origin yalgaeahn/local-work

git add KQCircuits
git add <SCDevice files>
git commit -m "Describe SCDevice change"
git push -u origin main
```

The order matters. If you changed `KQCircuits`, push that repository first. Only after the exact `KQCircuits` commit exists on your fork should you update and push the `SCDevice` submodule pointer.

User PCell changes should stay in `scdevice_pcells/` so upstream KQCircuits updates do not overwrite them.

## Troubleshooting

### `Unable to open file .../util/create_element_from_path.py`

This usually means the workspace root and task path do not match. In this repository, the VSCode task is supposed to run from the `SCDevice` root and call the top-level wrapper `util/create_element_from_path.py`. If you still see this error:

- make sure VSCode opened `SCDevice/`, not `SCDevice/KQCircuits/`
- make sure the file `SCDevice/util/create_element_from_path.py` exists
- if your KLayout install path differs from the default, update [.vscode/tasks.json](/Users/yalgaeahn/Research/20_Projects/SCDevice/.vscode/tasks.json)

### `create_element_from_path` Cannot Find `scdevice_pcells`

In the standard layout, `SCDevice/KQCircuits` automatically registers sibling `SCDevice/scdevice_pcells`. If that fails:

- confirm the repository still has the standard sibling layout
- confirm you are using the local modified `KQCircuits` checkout from this repo
- if the package lives elsewhere, set `KQC_EXTRA_SRC_PATHS`

### `git push` Does Not Behave The Way You Expect

`SCDevice` and `KQCircuits` are separate Git repositories with separate push targets.

- changes committed inside `KQCircuits` must be pushed from `KQCircuits`
- uncommitted changes inside `KQCircuits` are not included when you push `SCDevice`
- pushing `SCDevice` only updates the submodule pointer, not the submodule working tree

### `KQCircuits` Shows Up As A Dirty Submodule

That means `SCDevice` sees local changes inside the submodule working tree. The usual fix order is:

```bash
git -C KQCircuits status
git -C KQCircuits add <files>
git -C KQCircuits commit -m "Describe submodule change"
git -C KQCircuits push -u origin yalgaeahn/local-work

git status
git add KQCircuits
git commit -m "Update KQCircuits submodule pointer"
git push -u origin main
```

### `KQCircuits/` Looks Empty After Clone

If `KQCircuits/` is empty or missing expected files right after `git clone`, the submodule working tree has not been initialized yet.

Initialize the submodule:

```bash
git submodule update --init --recursive
```

Verify the checkout:

```bash
git submodule status
ls KQCircuits
```

Healthy output should show a commit hash for `KQCircuits` in `git submodule status`, and `ls KQCircuits` should show files such as `README.rst` and `klayout_package`.

### `Direct fetching of that commit failed`

This means submodule initialization started, but `SCDevice` points to an exact `KQCircuits` commit that your current machine cannot fetch from the remote fork.

`SCDevice` stores a submodule pointer, which is a specific `KQCircuits` commit hash, not just a branch name. Another machine can only check out `KQCircuits/` if that exact commit exists on the fork configured as the submodule remote.

Common causes:

- `KQCircuits` was committed locally but never pushed to your fork
- `SCDevice` was pushed after recording a submodule pointer to a local-only `KQCircuits` commit

Recovery path 1: the missing `KQCircuits` commit still exists on another machine.

- on the machine that still has the commit, go into `KQCircuits/`
- push the commit to your fork
- on the new machine, rerun `git submodule update --init --recursive`

Recovery path 2: the missing commit is gone and cannot be pushed anymore.

- on a machine with a valid `KQCircuits` checkout, move `KQCircuits/` to a real commit that exists on your fork
- from `SCDevice/`, run `git add KQCircuits`
- commit and push the updated `SCDevice` submodule pointer
- on the new machine, run `git pull` and then `git submodule update --init --recursive`

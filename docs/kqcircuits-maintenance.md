# KQCircuits Maintenance

SCDevice uses a fork of KQCircuits as a Git submodule. This document describes
how the two repositories are related and how to update them without losing the
SCDevice-specific KQCircuits changes.

## Repository Model

There are three relevant Git references:

- `upstream/main`: the official `iqm-finland/KQCircuits` repository
- `origin/scdevice-patches`: the SCDevice-specific branch on the
  `yalgaeahn/KQCircuits` fork
- `SCDevice/KQCircuits`: a submodule pointer to one exact commit from
  `origin/scdevice-patches`

The intended flow is:

```text
iqm-finland/KQCircuits upstream/main
                 |
                 | merge
                 v
yalgaeahn/KQCircuits scdevice-patches
                 |
                 | exact commit recorded by the submodule
                 v
              SCDevice
```

The `scdevice-patches` branch contains both the official upstream history and
the small KQCircuits changes required by SCDevice. Project-specific PCells that
do not require framework changes should remain under `scdevice_pcells/` in the
top-level repository.

## Initial Checkout

Clone SCDevice and check out the exact KQCircuits commit recorded by it:

```bash
git clone git@github.com:yalgaeahn/SCDevice.git
cd SCDevice
git submodule update --init --recursive
```

A submodule normally starts in detached HEAD state. That is expected when only
using the version pinned by SCDevice. Before editing or updating KQCircuits,
switch to the maintenance branch:

```bash
git -C KQCircuits switch scdevice-patches
```

If the local branch does not exist yet:

```bash
git -C KQCircuits switch --track origin/scdevice-patches
```

## Normal SCDevice Update

To update SCDevice to the versions already selected and tested by the project:

```bash
git pull
git submodule update --init --recursive
```

This checks out the KQCircuits commit recorded by SCDevice. It does not merge
new official KQCircuits releases.

## Bring In Official KQCircuits Updates

### 1. Verify clean working trees

Run from the SCDevice root:

```bash
git status
git -C KQCircuits status
```

Commit or intentionally stash existing work before continuing. Do not start an
upstream merge with unrelated uncommitted KQCircuits changes present.

### 2. Verify the remotes

```bash
git -C KQCircuits remote -v
```

The expected remotes are:

```text
origin    https://github.com/yalgaeahn/KQCircuits.git
upstream  https://github.com/iqm-finland/KQCircuits.git
```

If `upstream` is missing, add it once:

```bash
git -C KQCircuits remote add upstream https://github.com/iqm-finland/KQCircuits.git
```

### 3. Merge upstream into the patch branch

```bash
git -C KQCircuits switch scdevice-patches
git -C KQCircuits fetch upstream
git -C KQCircuits merge upstream/main
```

Use a regular merge for this long-lived shared branch. Do not force-push or
rebase published `scdevice-patches` history unless every consumer of the old
history has been coordinated.

If conflicts occur, resolve them inside `KQCircuits/`, test the result, stage
the resolved files, and finish the merge:

```bash
git -C KQCircuits add <resolved-files>
git -C KQCircuits commit
```

### 4. Test before publishing

At minimum, run the checks relevant to the affected code. With the project
environment activated, the KQCircuits test command is typically:

```bash
cd KQCircuits
python -m pytest -q <relevant-test-paths>
cd ..
```

Also open or generate the affected SCDevice layouts when the update changes
geometry, routing, library loading, or KLayout integration.

### 5. Push KQCircuits first

```bash
git -C KQCircuits push origin scdevice-patches
```

The KQCircuits commit must exist on the fork before SCDevice records it.
Otherwise, fresh clones of SCDevice will fail to fetch the submodule commit.

### 6. Record the new submodule pointer in SCDevice

```bash
git add KQCircuits
git commit -m "Update KQCircuits from upstream"
git push origin main
```

## Make an SCDevice-Specific KQCircuits Change

Only modify KQCircuits when the change belongs in the framework or integration
layer. Prefer `scdevice_pcells/` for project-specific chips, qubits, and
simulations.

```bash
git -C KQCircuits switch scdevice-patches

# Edit and test files under KQCircuits/.

git -C KQCircuits add <files>
git -C KQCircuits commit -m "Describe the KQCircuits change"
git -C KQCircuits push origin scdevice-patches

git add KQCircuits
git commit -m "Update KQCircuits submodule pointer"
git push origin main
```

Always push in this order:

1. Push the KQCircuits commit to the fork.
2. Commit and push the new submodule pointer in SCDevice.

## Useful Checks

Show the current pinned KQCircuits commit:

```bash
git submodule status KQCircuits
```

Compare the patch branch with official upstream:

```bash
git -C KQCircuits fetch upstream
git -C KQCircuits rev-list --left-right --count scdevice-patches...upstream/main
```

The two numbers mean:

- left: commits unique to `scdevice-patches`, including SCDevice patches and
  merge commits
- right: upstream commits not yet included in `scdevice-patches`

Inspect which KQCircuits commits a pending SCDevice pointer update introduces:

```bash
git diff --submodule=log -- KQCircuits
```

## Commands To Avoid

Avoid making changes while KQCircuits is in detached HEAD state. Switch to
`scdevice-patches` first.

Do not assume this command imports new official upstream changes:

```bash
git submodule update --remote KQCircuits
```

The `.gitmodules` file configures that command to follow the fork's
`scdevice-patches` branch. Official changes appear there only after
`upstream/main` has been merged and pushed using the workflow above.

Avoid force-pushing `scdevice-patches`; SCDevice may already point to commits
from its published history.

## Recovery

### KQCircuits is in detached HEAD state

This is normal after `git submodule update`. To resume development:

```bash
git -C KQCircuits switch scdevice-patches
```

If switching would overwrite local changes, stop and inspect them with
`git -C KQCircuits status` before doing anything else.

### SCDevice shows `M KQCircuits`

This means the KQCircuits working tree is dirty or checked out at a different
commit from the one recorded by SCDevice:

```bash
git -C KQCircuits status
git diff --submodule=log -- KQCircuits
```

Commit and push intentional KQCircuits work before updating the SCDevice
pointer. To return to the already recorded commit when no KQCircuits work needs
to be kept, use:

```bash
git submodule update --init KQCircuits
```

### A fresh clone cannot fetch the submodule commit

The usual cause is that SCDevice recorded a KQCircuits commit that was never
pushed to the fork. Push the missing commit from the machine that still has it,
then rerun:

```bash
git submodule update --init --recursive
```


---
name: codex-api-unlock
description: Rebuild a separate patched macOS Codex Fast.app from the current official /Applications/Codex.app after Codex updates, preserving the official app while overwriting or backing up the old Fast copy. Use when the user wants API-key mode Fast/Speed mode and Plugins in a non-official Codex app clone, or asks to refresh/recreate Codex Fast.app after installing an official Codex update.
---

# Codex API Unlock

Use this skill to rebuild a separate `/Applications/Codex Fast.app` from the current official `/Applications/Codex.app`. The workflow intentionally does not modify the official app.

## Default Workflow

Run the bundled script from the skill root:

```bash
python3 scripts/rebuild_codex_fast.py --yes --quit-target
```

The script:

1. Verifies `/Applications/Codex.app` and required tools (`ditto`, `npx`, `codesign`).
2. Moves an existing `/Applications/Codex Fast.app` to a timestamped backup unless `--no-backup` is passed.
3. Copies the official app to `/Applications/Codex Fast.app`.
4. Changes the copy identity to `Codex Fast` and `com.openai.codex.fast`.
5. Extracts the copied `app.asar`, patches API-key Fast/Plugins gates, repacks `app.asar`, and updates `ElectronAsarIntegrity`.
6. Removes stale unpacked app leftovers and signs/verifies the Fast copy.

## Common Commands

Overwrite old Fast copy after an official update, keeping a backup:

```bash
python3 scripts/rebuild_codex_fast.py --yes --quit-target
```

Overwrite old Fast copy without a backup:

```bash
python3 scripts/rebuild_codex_fast.py --yes --quit-target --no-backup
```

Use custom paths:

```bash
python3 scripts/rebuild_codex_fast.py --source /Applications/Codex.app --target "/Applications/Codex Fast.app" --yes --quit-target
```

Open the result:

```bash
open "/Applications/Codex Fast.app"
```

## Safety Rules

- Never patch `/Applications/Codex.app` directly.
- Treat failures that say "Required patch patterns were not found" as a Codex bundle update requiring manual pattern inspection.
- If `Codex Fast.app` opens to the Electron default page, rebuild with this skill; the packed `app.asar`, `ElectronAsarIntegrity` hash, or signature is stale.
- If the Fast copy is broken, delete it or restore from the timestamped backup. The official app should remain available.

## Expected Verification

After rebuilding and opening `Codex Fast.app`, verify:

- The app loads the Codex UI, not the Electron default page.
- API-key/custom-provider mode still works.
- Fast/Speed mode is visible or selectable.
- Plugins page/sidebar is visible.
- Plugin install does not mark all required apps/connectors unavailable.

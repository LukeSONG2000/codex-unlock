#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

DEFAULT_SOURCE = Path('/Applications/Codex.app')
DEFAULT_TARGET = Path('/Applications/Codex Fast.app')
DEFAULT_BUNDLE_ID = 'com.openai.codex.fast'

class PatchError(RuntimeError):
    pass

def run(cmd: list[str], *, cwd: Path | None = None) -> None:
    print('[RUN]', ' '.join(cmd))
    subprocess.run(cmd, cwd=cwd, check=True)

def capture(cmd: list[str]) -> str:
    return subprocess.check_output(cmd, text=True, stderr=subprocess.STDOUT)

def require_tool(name: str) -> None:
    if shutil.which(name) is None:
        raise SystemExit(f'Missing required tool: {name}')

def app_resources(app: Path) -> Path:
    return app / 'Contents' / 'Resources'

def info_plist(app: Path) -> Path:
    return app / 'Contents' / 'Info.plist'

def assert_source(source: Path) -> None:
    if not source.is_dir():
        raise SystemExit(f'Source app not found: {source}')
    if not (app_resources(source) / 'app.asar').is_file():
        raise SystemExit(f'Source app.asar not found: {app_resources(source) / "app.asar"}')
    if not info_plist(source).is_file():
        raise SystemExit(f'Source Info.plist not found: {info_plist(source)}')

def quit_target(target: Path) -> None:
    # Best-effort: helpers include the full bundle path in argv on macOS.
    subprocess.run(['pkill', '-f', str(target)], check=False)
    time.sleep(1)

def backup_or_remove_target(target: Path, *, yes: bool, backup: bool) -> Path | None:
    if not target.exists():
        return None
    if not yes:
        raise SystemExit(f'Target already exists: {target}\nRe-run with --yes to replace it.')
    if backup:
        stamp = time.strftime('%Y%m%d-%H%M%S')
        backup_path = target.with_name(f'{target.name}.backup-{stamp}')
        print(f'[OK] Moving existing target to backup: {backup_path}')
        target.rename(backup_path)
        return backup_path
    print(f'[OK] Removing existing target: {target}')
    shutil.rmtree(target)
    return None

def copy_app(source: Path, target: Path) -> None:
    # ditto handles macOS bundles and extended attributes better than shutil.copytree.
    run(['ditto', str(source), str(target)])

def set_plist_identity(app: Path, *, bundle_id: str, display_name: str) -> None:
    plist_path = info_plist(app)
    with plist_path.open('rb') as f:
        data = plistlib.load(f)
    data['CFBundleIdentifier'] = bundle_id
    data['CFBundleName'] = display_name
    data['CFBundleDisplayName'] = display_name
    with plist_path.open('wb') as f:
        plistlib.dump(data, f, sort_keys=False)

def update_asar_integrity(app: Path, asar_path: Path) -> None:
    digest = hashlib.sha256(asar_path.read_bytes()).hexdigest()
    plist_path = info_plist(app)
    with plist_path.open('rb') as f:
        data = plistlib.load(f)
    integrity = data.setdefault('ElectronAsarIntegrity', {})
    integrity['Resources/app.asar'] = {'hash': digest, 'algorithm': 'SHA256'}
    with plist_path.open('wb') as f:
        plistlib.dump(data, f, sort_keys=False)
    print(f'[OK] Updated ElectronAsarIntegrity hash: {digest}')

def replace_once(path: Path, old: str, new: str, label: str, actions: list[str]) -> None:
    text = path.read_text(encoding='utf-8')
    if old not in text:
        return
    path.write_text(text.replace(old, new, 1), encoding='utf-8')
    actions.append(f'{path.name}: {label}')
    print(f'[PATCHED] {path.name}: {label}')

def patch_assets(app_dir: Path) -> list[str]:
    assets = app_dir / 'webview' / 'assets'
    if not assets.is_dir():
        raise PatchError(f'Assets directory not found after extraction: {assets}')

    actions: list[str] = []

    for path in sorted(assets.glob('read-service-tier-for-request-*.js')):
        replace_once(
            path,
            'return n===`chatgpt`?(await e.query.fetch(c,{authMethod:n,hostId:t})).requirements?.featureRequirements?.fast_mode!==!1:!1',
            'return n===`chatgpt`?(await e.query.fetch(c,{authMethod:n,hostId:t})).requirements?.featureRequirements?.fast_mode!==!1:!0',
            'API-key request service-tier allowed',
            actions,
        )

    for path in sorted(assets.glob('use-service-tier-settings-*.js')):
        replace_once(path, 'a=i?.authMethod===`chatgpt`', 'a=!0', 'service-tier auth gate allowed', actions)
        replace_once(
            path,
            'u=!!i?.isLoading||a&&l,f=a&&!u&&c!=null&&c?.requirements?.featureRequirements?.fast_mode!==!1',
            'u=!!i?.isLoading,f=a&&!u',
            'service-tier loading/feature gate allowed',
            actions,
        )

    for path in sorted(assets.glob('use-plugins-*.js')):
        replace_once(path, 'function ge(e){return e!==`chatgpt`}', 'function ge(e){return false}', 'API-key plugin gate disabled', actions)
        replace_once(
            path,
            'return!(!r&&Re(e)||!n&&ze(e)||!t&&Be(e))',
            'return!(!r&&Re(e)||!t&&Be(e))',
            'Chrome plugin external-browser gate removed',
            actions,
        )

    for path in sorted(assets.glob('check-plugin-availability-*.js')):
        replace_once(
            path,
            '(r||n!=null&&!n.isPending&&n.error==null&&n.data==null)&&(i=`connector-unavailable`)',
            'false&&(r||n!=null&&!n.isPending&&n.error==null&&n.data==null)&&(i=`connector-unavailable`)',
            'connector-unavailable per-app gate disabled',
            actions,
        )
        replace_once(
            path,
            'let F=b.length>0&&N===b.length?M?`disabled-by-admin`:`connector-unavailable`:null',
            'let F=b.length>0&&N===b.length&&M?`disabled-by-admin`:null',
            'connector-unavailable aggregate gate disabled',
            actions,
        )

    required_fragments = [
        'API-key request service-tier allowed',
        'service-tier auth gate allowed',
        'API-key plugin gate disabled',
    ]
    missing = [frag for frag in required_fragments if not any(frag in action for action in actions)]
    if missing:
        raise PatchError(
            'Required patch patterns were not found. Codex bundle likely changed. Missing: '
            + ', '.join(missing)
        )
    return actions

def patch_asar(target: Path) -> list[str]:
    resources = app_resources(target)
    original_asar = resources / 'app.asar'
    if not original_asar.is_file():
        raise SystemExit(f'Target app.asar not found: {original_asar}')
    backup_asar = resources / 'app.asar.bak'
    shutil.copy2(original_asar, backup_asar)
    print(f'[OK] Backed up target app.asar -> {backup_asar}')

    with tempfile.TemporaryDirectory(prefix='codex-fast-clone-') as temp:
        temp_dir = Path(temp)
        extracted = temp_dir / 'app'
        patched_asar = temp_dir / 'app.asar'
        run(['npx', '@electron/asar', 'e', str(original_asar), str(extracted)])
        actions = patch_assets(extracted)
        run(['npx', '@electron/asar', 'p', str(extracted), str(patched_asar)])
        shutil.copy2(patched_asar, original_asar)
        print(f'[OK] Wrote patched app.asar -> {original_asar}')

    # Remove unpacked app leftovers from older manual patch attempts.
    for stale in (resources / 'app', resources / 'app.asar1'):
        if stale.is_dir():
            shutil.rmtree(stale)
            print(f'[OK] Removed stale directory: {stale}')
        elif stale.exists():
            stale.unlink()
            print(f'[OK] Removed stale file: {stale}')
    return actions

def verify(app: Path) -> None:
    run(['codesign', '--force', '--deep', '--sign', '-', str(app)])
    run(['codesign', '--verify', '--deep', '--strict', '--verbose=2', str(app)])

def main() -> None:
    parser = argparse.ArgumentParser(description='Rebuild a patched Codex Fast.app from the official Codex.app without modifying the official app.')
    parser.add_argument('--source', type=Path, default=DEFAULT_SOURCE, help='Official Codex.app path')
    parser.add_argument('--target', type=Path, default=DEFAULT_TARGET, help='Patched Fast app path')
    parser.add_argument('--bundle-id', default=DEFAULT_BUNDLE_ID, help='Bundle identifier for the Fast copy')
    parser.add_argument('--display-name', default='Codex Fast', help='Display name for the Fast copy')
    parser.add_argument('--yes', action='store_true', help='Replace existing target app')
    parser.add_argument('--no-backup', action='store_true', help='Delete existing target instead of moving it to a timestamped backup')
    parser.add_argument('--quit-target', action='store_true', help='Best-effort quit of the target app before replacing it')
    args = parser.parse_args()

    require_tool('ditto')
    require_tool('npx')
    require_tool('codesign')
    assert_source(args.source)

    if args.quit_target:
        quit_target(args.target)
    backup_path = backup_or_remove_target(args.target, yes=args.yes, backup=not args.no_backup)
    copy_app(args.source, args.target)
    set_plist_identity(args.target, bundle_id=args.bundle_id, display_name=args.display_name)
    actions = patch_asar(args.target)
    update_asar_integrity(args.target, app_resources(args.target) / 'app.asar')
    verify(args.target)

    print('\n=== Codex Fast clone complete ===')
    print(f'Source: {args.source}')
    print(f'Target: {args.target}')
    if backup_path:
        print(f'Previous target backup: {backup_path}')
    print('Patch actions:')
    for action in actions:
        print(f'  - {action}')
    print(f'Open with: open {str(args.target)!r}')

if __name__ == '__main__':
    try:
        main()
    except subprocess.CalledProcessError as exc:
        print(f'Command failed: {exc}', file=sys.stderr)
        raise SystemExit(exc.returncode)
    except PatchError as exc:
        print(f'Patch failed: {exc}', file=sys.stderr)
        raise SystemExit(2)

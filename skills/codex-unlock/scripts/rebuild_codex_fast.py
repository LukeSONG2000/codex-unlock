#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import os
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

DEFAULT_SOURCE = Path('/Applications/Codex.app')
DEFAULT_TARGET = Path('/Applications/Codex Fast.app')
DEFAULT_BUNDLE_ID = 'com.openai.codex.fast'
DEFAULT_SIGN_IDENTITY = 'Codex Unlock Local Code Signing'
LOCAL_CERT_IMPORT_PASSWORD = 'codex-unlock-local'

class PatchError(RuntimeError):
    pass

def run(cmd: list[str], *, cwd: Path | None = None) -> None:
    print('[RUN]', ' '.join(cmd))
    subprocess.run(cmd, cwd=cwd, check=True)

def require_tool(name: str) -> None:
    if shutil.which(name) is None:
        raise SystemExit(f'Missing required tool: {name}')


def has_local_signing_certificate(identity: str) -> bool:
    completed = subprocess.run(
        ['security', 'find-certificate', '-c', identity, '-a', str(Path.home() / 'Library/Keychains/login.keychain-db')],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    return identity in completed.stdout

def ensure_local_signing_certificate(identity: str) -> None:
    if identity == '-':
        return
    if has_local_signing_certificate(identity):
        return
    require_tool('openssl')
    with tempfile.TemporaryDirectory(prefix='codex-unlock-cert-') as temp:
        temp_dir = Path(temp)
        config = temp_dir / 'openssl.cnf'
        key = temp_dir / 'key.pem'
        cert = temp_dir / 'cert.pem'
        p12 = temp_dir / 'cert.p12'
        config.write_text(
            '[ req ]\n'
            'distinguished_name = dn\n'
            'x509_extensions = v3_req\n'
            'prompt = no\n\n'
            '[ dn ]\n'
            f'CN = {identity}\n\n'
            '[ v3_req ]\n'
            'keyUsage = critical, digitalSignature\n'
            'extendedKeyUsage = codeSigning\n'
            'basicConstraints = critical, CA:false\n'
            'subjectKeyIdentifier = hash\n',
            encoding='utf-8',
        )
        run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '3650', '-config', str(config), '-keyout', str(key), '-out', str(cert)])
        run(['openssl', 'pkcs12', '-legacy', '-export', '-out', str(p12), '-inkey', str(key), '-in', str(cert), '-passout', f'pass:{LOCAL_CERT_IMPORT_PASSWORD}'])
        run(['security', 'import', str(p12), '-k', str(Path.home() / 'Library/Keychains/login.keychain-db'), '-P', LOCAL_CERT_IMPORT_PASSWORD, '-T', '/usr/bin/codesign'])
    print(f'[OK] Created local signing certificate: {identity}')

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

def replace_regex(path: Path, pattern: str, replacement: str, label: str, actions: list[str]) -> None:
    text = path.read_text(encoding='utf-8')
    new, n = re.subn(pattern, replacement, text, count=1)
    if n == 0:
        return
    path.write_text(new, encoding='utf-8')
    actions.append(f'{path.name}: {label}')
    print(f'[PATCHED] {path.name}: {label}')

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

    # 1) read-service-tier-for-request: allow API-key requests to use fast service tier
    for path in sorted(assets.glob('read-service-tier-for-request-*.js')):
        replace_regex(
            path,
            r'return n===`chatgpt`\?\(await e\.query\.fetch\(c,\{authMethod:n,hostId:t\}\)\)\.requirements\?\.featureRequirements\?\.fast_mode!==!1:!1',
            'return n===`chatgpt`?(await e.query.fetch(c,{authMethod:n,hostId:t})).requirements?.featureRequirements?.fast_mode!==!1:!0',
            'API-key request service-tier allowed',
            actions,
        )

    # 2) use-service-tier-settings: gate UI on auth=chatgpt. Variable names vary across builds,
    #    so match by the stable expression `?.authMethod===`chatgpt`` and the feature flag line.
    for path in sorted(assets.glob('use-service-tier-settings-*.js')):
        replace_regex(
            path,
            r'(\w+)\?\.authMethod===`chatgpt`',
            r'\1?.authMethod===`chatgpt`||!0',
            'service-tier auth gate allowed',
            actions,
        )
        replace_regex(
            path,
            r'(\w+)=(!!(\w+)\?\.isLoading\|\|(\w+)&&(\w+)),(\w+)=\4&&!\5&&(\w+)!=null&&\6\?\.requirements\?\.featureRequirements\?\.fast_mode!==!1',
            r'\1=\2,\6=\4||!0&&!5',
            'service-tier loading/feature gate allowed',
            actions,
        )

    # 3) use-plugins: API-key plugin gate function returns `e!==`chatgpt``. Function name varies.
    for path in sorted(assets.glob('use-plugins-*.js')):
        replace_regex(
            path,
            r'function (\w+)\((\w+)\)\{return \2!==`chatgpt`\}',
            r'function \1(\2){return false}',
            'API-key plugin gate disabled',
            actions,
        )
        # Chrome plugin external-browser gate: `!n&&ze(e)` where ze matches chrome plugin types.
        # Match the stable `Le` filter expression shape regardless of minifier names.
        replace_regex(
            path,
            r'return!\(!r&&(\w+)\((\w+)\)\|\|!n&&(\w+)\(\2\)\|\|!t&&(\w+)\(\2\)\)',
            r'return!(!r&&\1(\2)||!t&&\4(\2))',
            'Chrome plugin external-browser gate removed',
            actions,
        )

    # 4) check-plugin-availability: stop marking apps as connector-unavailable.
    for path in sorted(assets.glob('check-plugin-availability-*.js')):
        # Per-app connector-unavailable guard shape changes across builds; neutralize by
        # prefixing the connector-unavailable assignment with a false short-circuit.
        replace_regex(
            path,
            r'\(([^`]{0,120}?)&&\((\w+)=`connector-unavailable`\)\)',
            r'(false&&\2=`connector-unavailable`)',
            'connector-unavailable per-app gate disabled',
            actions,
        )
        replace_regex(
            path,
            r'let (\w+)=(\w+)\.length>0&&(\w+)===\2\.length\?(\w+)\?`disabled-by-admin`:`connector-unavailable`:null',
            r'let \1=\2.length>0&&\3===\2.length&&\4?`disabled-by-admin`:null',
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

    with tempfile.TemporaryDirectory(prefix='codex-unlock-') as temp:
        temp_dir = Path(temp)
        extracted = temp_dir / 'app'
        patched_asar = temp_dir / 'app.asar'
        run(['npx', '@electron/asar', 'e', str(original_asar), str(extracted)])
        actions = patch_assets(extracted)
        run(['npx', '@electron/asar', 'p', str(extracted), str(patched_asar)])
        shutil.copy2(patched_asar, original_asar)
        print(f'[OK] Wrote patched app.asar -> {original_asar}')

    for stale in (resources / 'app', resources / 'app.asar1'):
        if stale.is_dir():
            shutil.rmtree(stale)
            print(f'[OK] Removed stale directory: {stale}')
        elif stale.exists():
            stale.unlink()
            print(f'[OK] Removed stale file: {stale}')
    return actions

def verify(app: Path, sign_identity: str) -> None:
    ensure_local_signing_certificate(sign_identity)
    run(['codesign', '--force', '--deep', '--sign', sign_identity, str(app)])
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
    parser.add_argument('--sign-identity', default=DEFAULT_SIGN_IDENTITY, help='Code signing identity for the Fast copy; default creates/reuses a stable local certificate')
    parser.add_argument('--ad-hoc-sign', action='store_true', help='Use ad-hoc signing instead of the stable local certificate')
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
    sign_identity = '-' if args.ad_hoc_sign else args.sign_identity
    verify(args.target, sign_identity)

    print('\n=== Codex Fast clone complete ===')
    print(f'Source: {args.source}')
    print(f'Target: {args.target}')
    print(f'Sign identity: {sign_identity}')
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

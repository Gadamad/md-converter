"""Install a verified macOS bundle while retaining a recoverable previous copy."""
import argparse
from datetime import datetime
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time
import uuid


def verify(app):
    if not (app / 'Contents' / 'MacOS' / 'MD Converter').is_file():
        raise ValueError(f'Not an MD Converter bundle: {app}')
    subprocess.run(['/usr/bin/codesign', '--verify', '--deep', '--strict', str(app)], check=True)


def running_pids(destination):
    executable = str(destination / 'Contents' / 'MacOS' / 'MD Converter')
    output = subprocess.check_output(['/bin/ps', '-axo', 'pid=,command='], text=True)
    result = []
    for line in output.splitlines():
        parts = line.strip().split(maxsplit=1)
        if len(parts) == 2 and (parts[1] == executable or parts[1].startswith(executable + ' ')):
            result.append(int(parts[0]))
    return result


def copy_bundle(source, target):
    subprocess.run(['/usr/bin/ditto', str(source), str(target)], check=True)


def install(source: Path, destination: Path, backup_dir: Path, close_running=False):
    verify(source)
    if source.resolve() == destination.resolve():
        raise ValueError('Build and installation paths must be different')
    active = running_pids(destination)
    if active and not close_running:
        raise RuntimeError('Close MD Converter first, or explicitly use --close-running.')
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = destination.parent / f'.MD-Converter-install-{uuid.uuid4().hex}.app'
    retired = destination.parent / f'.MD-Converter-previous-{uuid.uuid4().hex}.app'
    backup = None
    try:
        copy_bundle(source, staging)
        verify(staging)
        if destination.exists():
            backup_dir.mkdir(parents=True, exist_ok=True)
            backup = backup_dir / f'MD Converter-{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}.app'
            copy_bundle(destination, backup)
        if active:
            # Match executable paths again immediately before signaling; do not
            # stop another build or unrelated Python process with the same name.
            for pid in running_pids(destination):
                try:
                    os.kill(pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            deadline = time.monotonic() + 5
            while running_pids(destination):
                if time.monotonic() >= deadline:
                    raise RuntimeError('The running app did not close; the existing installation has been retained.')
                time.sleep(.1)
        if destination.exists():
            os.replace(destination, retired)
        try:
            os.replace(staging, destination)
        except BaseException:
            if retired.exists():
                os.replace(retired, destination)
            raise
        if retired.exists():
            shutil.rmtree(retired)
        return backup
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def main():
    project = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=project / 'src/dist/MD Converter.app')
    parser.add_argument('--destination', type=Path, default=Path('/Applications/MD Converter.app'))
    parser.add_argument('--backup-dir', type=Path, default=project / 'release-backups')
    parser.add_argument('--close-running', action='store_true')
    args = parser.parse_args()
    backup = install(args.source, args.destination, args.backup_dir, args.close_running)
    print(f'Installed: {args.destination}')
    if backup:
        print(f'Previous version: {backup}')


if __name__ == '__main__':
    main()

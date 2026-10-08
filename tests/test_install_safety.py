import importlib.util
from pathlib import Path
from unittest import mock
import shutil
import pytest

spec = importlib.util.spec_from_file_location('install_app', Path(__file__).resolve().parents[1] / 'scripts/install_app.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


def bundles(tmp_path):
    source, dest = tmp_path / 'build.app', tmp_path / 'Applications/app.app'
    for path, value in ((source, 'new'), (dest, 'old')):
        path.mkdir(parents=True)
        (path / 'version').write_text(value)
    return source, dest


def test_install_preserves_previous_bundle(tmp_path):
    source, dest = bundles(tmp_path)
    with mock.patch.object(installer, 'verify'), mock.patch.object(installer, 'running_pids', return_value=[]), mock.patch.object(installer, 'copy_bundle', side_effect=shutil.copytree):
        backup = installer.install(source, dest, tmp_path / 'backups')
    assert (backup / 'version').read_text() == 'old'
    assert (dest / 'version').read_text() == 'new'


def test_failed_replacement_restores_original(tmp_path):
    source, dest = bundles(tmp_path)
    replace = installer.os.replace
    def fail_install(old, new):
        if old.name.startswith('.MD-Converter-install'):
            raise OSError('disk unavailable')
        replace(old, new)
    with mock.patch.object(installer, 'verify'), mock.patch.object(installer, 'running_pids', return_value=[]), mock.patch.object(installer, 'copy_bundle', side_effect=shutil.copytree), mock.patch.object(installer.os, 'replace', side_effect=fail_install), pytest.raises(OSError):
        installer.install(source, dest, tmp_path / 'backups')
    assert (dest / 'version').read_text() == 'old'
    assert not list(dest.parent.glob('.MD-Converter-*'))


def test_installer_requires_explicit_close_for_running_app(tmp_path):
    source, dest = bundles(tmp_path)
    with mock.patch.object(installer, 'verify'), mock.patch.object(installer, 'running_pids', return_value=[123]), pytest.raises(RuntimeError, match='Close MD Converter'):
        installer.install(source, dest, tmp_path / 'backups')
    assert (dest / 'version').read_text() == 'old'

import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('update_stack', Path(__file__).resolve().parents[1] / 'tools/update_stack.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class DeploymentUpdateTests(unittest.TestCase):
    def git(self, *args, cwd=None):
        return subprocess.check_output(['git', *args], cwd=cwd or self.repo, stderr=subprocess.STDOUT, text=True)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.remote = root / 'remote.git'
        self.repo = root / 'live'
        self.git('init', '--bare', str(self.remote), cwd=root)
        self.git('clone', str(self.remote), str(self.repo), cwd=root)
        self.git('config', 'user.email', 'test@example.test')
        self.git('config', 'user.name', 'Test')
        self.git('checkout', '-b', 'main')
        self.config = self.repo / 'macos/Caddyfile'
        self.config.parent.mkdir()
        self.base = ''.join(f'line {i}\n' for i in range(20))
        self.config.write_text(self.base)
        self.git('add', '.')
        self.git('commit', '-m', 'base')
        self.git('push', '-u', 'origin', 'main')
        self.old_head = self.git('rev-parse', 'HEAD').strip()
        self.author = root / 'author'
        self.git('clone', '-b', 'main', str(self.remote), str(self.author), cwd=root)
        self.git('config', 'user.email', 'test@example.test', cwd=self.author)
        self.git('config', 'user.name', 'Test', cwd=self.author)
        self.updater = module.Updater(root / 'status.json')
        self.root_patch = patch.object(module, 'REPO_ROOT', self.repo)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)

    def upstream(self, text):
        (self.author / 'macos/Caddyfile').write_text(text)
        self.git('add', '.', cwd=self.author)
        self.git('commit', '-m', 'upstream', cwd=self.author)
        self.git('push', cwd=self.author)
        self.git('fetch', 'origin', 'main')

    def test_merges_configuration_and_keeps_recoverable_backup(self):
        self.upstream(self.base.replace('line 18\n', 'upstream 18\n'))
        local = self.base.replace('line 1\n', 'local 1\n')
        self.config.write_text(local)
        (self.repo / 'untracked.txt').write_text('keep')
        self.updater.pull_preserving_deployment()
        self.assertEqual(self.git('rev-parse', 'HEAD'), self.git('rev-parse', 'origin/main'))
        self.assertEqual(self.config.read_text(), local.replace('line 18\n', 'upstream 18\n'))
        self.assertEqual(self.git('show', 'stash@{0}:macos/Caddyfile'), local)
        self.assertEqual((self.repo / 'untracked.txt').read_text(), 'keep')
        self.assertEqual(self.git('diff', '--cached'), '')

    def test_conflict_leaves_live_configuration_and_head_untouched(self):
        self.upstream(self.base.replace('line 1\n', 'upstream 1\n'))
        local = self.base.replace('line 1\n', 'local 1\n')
        self.config.write_text(local)
        with self.assertRaisesRegex(RuntimeError, 'macos/Caddyfile'):
            self.updater.pull_preserving_deployment()
        self.assertEqual(self.config.read_text(), local)
        self.assertEqual(self.git('rev-parse', 'HEAD').strip(), self.old_head)
        self.assertEqual(json.loads(self.updater.status_file.read_text())['step'], 'preflight')

    def test_failed_pull_restores_local_configuration(self):
        self.upstream(self.base.replace('line 18\n', 'upstream 18\n'))
        (self.repo / 'source.txt').write_text('local commit')
        self.git('add', 'source.txt')
        self.git('commit', '-m', 'diverged')
        head = self.git('rev-parse', 'HEAD')
        local = self.base.replace('line 1\n', 'local 1\n')
        self.config.write_text(local)
        with self.assertRaisesRegex(RuntimeError, 'git-pull failed'):
            self.updater.pull_preserving_deployment()
        self.assertEqual(self.config.read_text(), local)
        self.assertEqual(self.git('rev-parse', 'HEAD'), head)
        self.assertEqual(json.loads(self.updater.status_file.read_text())['step'], 'git-pull')

    def test_staged_configuration_is_not_modified(self):
        self.upstream(self.base.replace('line 18\n', 'upstream 18\n'))
        self.config.write_text(self.base.replace('line 1\n', 'local 1\n'))
        self.git('add', 'macos/Caddyfile')
        staged = self.git('diff', '--cached')
        with self.assertRaises(RuntimeError):
            self.updater.pull_preserving_deployment()
        self.assertEqual(self.git('diff', '--cached'), staged)

    def test_main_keeps_specific_failure_step(self):
        def fail(updater):
            updater.run('git-pull', ['git', 'definitely-not-a-command'])
        with patch.object(module.Updater, 'execute', fail), patch.object(module.sys, 'argv', ['update_stack', '--status-file', str(self.updater.status_file)]):
            self.assertEqual(module.main(), 1)
        status = json.loads(self.updater.status_file.read_text())
        self.assertEqual(status['step'], 'git-pull')
        self.assertEqual(status['entries'][-1]['step'], 'git-pull')


class UpdateStatusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location('session_control_update', Path(__file__).resolve().parents[1] / 'session-control.py')
        cls.control = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.control)

    def test_legacy_fatal_entry_does_not_hide_git_error(self):
        status = self.control.humanize_operation_status({
            'state': 'failed', 'entries': [
                {'step': 'git-pull', 'ok': False, 'message': 'exit 1'},
                {'step': 'fatal', 'ok': False, 'message': 'git-pull failed'},
            ],
        }, 'update')
        self.assertIn('origin/main', status['summary'])

    def test_conflicting_configuration_path_is_visible(self):
        message = 'Конфликт локальных настроек с обновлением: macos/Caddyfile'
        status = self.control.humanize_operation_status({
            'state': 'failed', 'entries': [{'step': 'preflight', 'ok': False, 'message': message}],
        }, 'update')
        self.assertEqual(status['summary'], message)


if __name__ == '__main__':
    unittest.main()

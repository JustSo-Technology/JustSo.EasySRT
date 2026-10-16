"""Deployment regression tests: execute isolated functions without touching a host."""
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest

OPS = Path(__file__).parent


def function(script, name):
    text = (OPS / script).read_text()
    start = text.index(f'{name}() {{')
    end = text.index('\n}\n', start) + 3
    return text[start:end]


class DeploymentTests(unittest.TestCase):
    def run_shell(self, body, env=None):
        return subprocess.run(['bash', '-c', 'set -eu\n' + body], capture_output=True, text=True, env=env)

    def make_repo(self, directory):
        repo = Path(directory, 'repo')
        repo.mkdir()
        def git(*args):
            return subprocess.check_output(['git', '-C', str(repo), *args], text=True).strip()
        git('init', '-q')
        git('config', 'user.email', 'test@example.test')
        git('config', 'user.name', 'Deployment test')
        git('remote', 'add', 'origin', 'https://example.test/original.git')
        Path(repo, 'fix.txt').write_text('base\n')
        git('add', '.')
        git('commit', '-qm', 'original')
        original = git('rev-parse', 'HEAD')
        Path(repo, 'fix.txt').write_text('updated version\n')
        git('commit', '-qam', 'update')
        target = git('rev-parse', 'HEAD')
        git('checkout', '-q', '--detach', original)
        Path(repo, 'fix.txt').write_text('staged local fix\n')
        git('add', 'fix.txt')
        Path(repo, 'fix.txt').write_text('unstaged local fix\n')
        Path(repo, 'local.txt').write_text('untracked local fix\n')
        return repo, git, original, target

    def test_target_resolution_failure_preserves_local_fixes(self):
        with tempfile.TemporaryDirectory() as directory:
            repo, git, _, _ = self.make_repo(directory)
            before = git('status', '--porcelain')
            noops = ('print_banner ensure_update_tracking write_update_state step detect_host '
                     'assert_supported_ubuntu info ok ensure_sudo verify_existing_install '
                     'apt_install_if_missing ensure_node_runtime ensure_pnpm assert_python_version '
                     'ensure_uv create_backup prune_old_backups record_log')
            body = '\n'.join(f'{name}() {{ :; }}' for name in noops.split())
            body += '''
sudo() { if [[ "$1" == -u ]]; then shift 2; fi; command "$@"; }
date() { printf 'test-time\\n'; }
prepare_privileged_source() { return 1; }
OS_NAME=Ubuntu OS_VERSION=24 KERNEL_VERSION=test REPO_REF=main CURRENT_COMMIT=test
''' + function('update-ubuntu.sh', 'stash_local_changes') + function('update-ubuntu.sh', 'main') + '\nmain'
            result = self.run_shell(body, {**os.environ, 'APP_DIR': str(repo), 'APP_USER': 'test', 'BACKUP_PATH': directory})
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(git('status', '--porcelain'), before)
            self.assertEqual(Path(repo, 'fix.txt').read_text(), 'unstaged local fix\n')
            self.assertEqual(git('remote', 'get-url', 'origin'), 'https://example.test/original.git')

    def test_rollback_restores_local_fixes_and_index_before_rebuild(self):
        with tempfile.TemporaryDirectory() as directory:
            repo, git, original, target = self.make_repo(directory)
            before = git('status', '--porcelain')
            backup = Path(directory, 'backup')
            backup.mkdir()
            Path(backup, 'easysrt.env').write_text('original environment\n')
            data = Path(repo, 'backend/data')
            data.mkdir(parents=True)
            subprocess.run(['tar', '-C', str(data), '-cf', str(backup / 'data.tar'), '.'], check=True)
            git('stash', 'push', '--include-untracked', '-qm', 'original local fixes')
            stash = git('rev-parse', 'stash@{0}')
            git('checkout', '-q', '--detach', target)
            body = '''
sudo() { if [[ "$1" == -u ]]; then shift 2; fi; if [[ "$1" == systemctl ]]; then return 0; fi; command "$@"; }
warn() { :; }
record_log() { :; }
write_update_state() { :; }
ensure_config_permissions() { :; }
install_backend() { [[ "$(cat "$APP_DIR/fix.txt")" == 'unstaged local fix' ]]; }
install_frontend() { :; }
install_services() { :; }
health_check() { :; }
date() { printf 'test-time\\n'; }
''' + function('update-ubuntu.sh', 'rollback_update') + '\nrollback_update'
            result = self.run_shell(body, {**os.environ, 'APP_DIR': str(repo), 'APP_USER': 'test',
                'CURRENT_COMMIT': original, 'ORIGINAL_ORIGIN': 'https://example.test/original.git',
                'STASH_REF': stash, 'BACKUP_PATH': str(backup), 'CONFIG_DIR': str(Path(directory, 'config')),
                'ENV_FILE': str(Path(directory, 'config/easysrt.env')), 'BACKEND_DIR': str(repo / 'backend')})
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(git('rev-parse', 'HEAD'), original)
            self.assertEqual(git('status', '--porcelain'), before)
            self.assertEqual(git('show', ':fix.txt'), 'staged local fix')
            self.assertEqual(Path(repo, 'local.txt').read_text(), 'untracked local fix\n')
            self.assertEqual(git('rev-parse', 'stash@{0}'), stash)

    def test_failed_fetch_does_not_change_origin_or_working_tree(self):
        with tempfile.TemporaryDirectory() as directory:
            repo, git, _, _ = self.make_repo(directory)
            before = git('status', '--porcelain')
            body = '''
sudo() { shift 2; if [[ "$4" == fetch ]]; then return 9; fi; command "$@"; }
ensure_repo_token_if_needed() { :; }
build_clone_url() { printf 'https://example.test/target.git'; }
''' + function('update-ubuntu.sh', 'prepare_target_commit') + '\nprepare_target_commit'
            result = self.run_shell(body, {**os.environ, 'APP_DIR': str(repo), 'APP_USER': 'test',
                'REPO_URL': 'https://example.test/target.git', 'TRUSTED_COMMIT': 'abc'})
            self.assertEqual(result.returncode, 9, result.stderr)
            self.assertEqual(git('status', '--porcelain'), before)
            self.assertEqual(git('remote', 'get-url', 'origin'), 'https://example.test/original.git')

    def test_backup_quiesces_writer_and_restores_prior_backend_state_even_on_failure(self):
        for active in ('yes', 'no'):
            for fail in ('yes', 'no'):
                with self.subTest(active=active, fail=fail), tempfile.TemporaryDirectory() as directory:
                    data = Path(directory, 'data')
                    data.mkdir()
                    Path(data, 'settings.json').write_text('{"setting": "original"}')
                    body = '''
set -o pipefail
sudo() {
  if [[ "$1" == -u ]]; then shift 2; fi
  if [[ "$1" == systemctl ]]; then
    printf '%s\\n' "$2" >> "$BACKUP_PATH/service-actions"
    case "$2" in
      is-active) [[ "$ACTIVE" == yes ]];;
      stop) touch "$BACKUP_PATH/stopped";;
      start) rm "$BACKUP_PATH/stopped";;
    esac
    return
  fi
  if [[ "$1" == tar ]]; then
    [[ -f "$BACKUP_PATH/stopped" ]] || return 8
    [[ "$ARCHIVE_FAIL" != yes ]] || return 9
  fi
  command "$@"
}
''' + function('update-ubuntu.sh', 'create_data_backup') + '\ncreate_data_backup'
                    result = self.run_shell(body, {**os.environ, 'BACKUP_PATH': directory,
                        'BACKEND_DIR': directory, 'APP_USER': 'test', 'ACTIVE': active, 'ARCHIVE_FAIL': fail})
                    self.assertEqual(result.returncode, 9 if fail == 'yes' else 0, result.stderr)
                    actions = Path(directory, 'service-actions').read_text().splitlines()
                    self.assertEqual(actions, ['is-active', 'stop'] + (['start'] if active == 'yes' else []))
                    if fail == 'no':
                        with tarfile.open(Path(directory, 'data.tar')) as archive:
                            self.assertEqual(json.load(archive.extractfile('./settings.json')), {'setting': 'original'})

    def test_node_supported_versions(self):
        for script in ('install-ubuntu.sh', 'update-ubuntu.sh'):
            for version, accepted in [('20.18.3', False), ('20.19.0', True), ('21.9.0', False), ('22.11.0', False), ('22.12.0', True), ('24.0.0', True)]:
                with self.subTest(script=script, version=version):
                    # Run the real JavaScript predicate with a substituted version.
                    predicate = function(script, 'node_runtime_supported').replace('process.versions.node', json.dumps(version))
                    result = self.run_shell(predicate + '\nnode_runtime_supported')
                    self.assertEqual(result.returncode == 0, accepted, result.stderr)

    def test_backend_refuses_missing_lock_and_uses_locked_sync(self):
        for script in ('install-ubuntu.sh', 'update-ubuntu.sh'):
            with self.subTest(script=script), tempfile.TemporaryDirectory() as directory:
                env = {**os.environ, 'BACKEND_DIR': directory, 'TOOLS_DIR': '/trusted-tools', 'APP_USER': 'easysrt'}
                body = '''info() { :; }
ok() { :; }
die() { echo "$1" >&2; exit 1; }
sudo() { printf '%s\\n' "$@"; }
''' + function(script, 'install_backend') + '\ninstall_backend'
                result = self.run_shell(body, env)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('refusing an unlocked', result.stderr)
                Path(directory, 'uv.lock').touch()
                result = self.run_shell(body, env)
                self.assertEqual(result.returncode, 0, result.stderr)
                args = result.stdout.splitlines()
                self.assertEqual(args[:4], ['-u', 'easysrt', '/trusted-tools/bin/uv', 'sync'])
                for flag in ('--locked', '--no-dev', '--no-editable'):
                    self.assertIn(flag, args)

    def test_rollback_build_and_service_failures_cannot_report_success(self):
        # Bash disables errexit inside functions called by `if`/`||`, including
        # rollback's nested install functions. Every critical failure must return.
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, 'uv.lock').touch()
            env = {**os.environ, 'BACKEND_DIR': directory, 'FRONTEND_DIR': directory,
                   'APP_DIR': directory, 'APP_USER': 'test', 'TOOLS_DIR': directory,
                   'PRIVILEGED_DIR': directory, 'PRIVILEGED_SOURCE': directory}
            for name in ('install_backend', 'install_frontend', 'install_services', 'install_privileged_files', 'ensure_config_permissions'):
                with self.subTest(function=name):
                    body = '''
info() { :; }
ok() { :; }
record_log() { :; }
sudo() { return 42; }
install_privileged_files() { return 42; }
''' + function('update-ubuntu.sh', name) + f'\nif {name}; then exit 0; else exit 42; fi'
                    result = self.run_shell(body, {**env, 'CONFIG_DIR': directory, 'ENV_FILE': directory, 'APP_GROUP': 'test'})
                    self.assertEqual(result.returncode, 42, result.stderr)

    def test_token_cannot_change_clone_host(self):
        for script in ('install-ubuntu.sh', 'update-ubuntu.sh'):
            with self.subTest(script=script):
                body = 'die() { exit 1; }\n' + function(script, 'build_clone_url') + '\nbuild_clone_url'
                env = {**os.environ, 'REPO_URL': 'https://github.com/example/repo.git', 'GITHUB_TOKEN': '@attacker.example/#'}
                self.assertNotEqual(self.run_shell(body, env).returncode, 0)
                env['GITHUB_TOKEN'] = 'github_pat_abc123'
                result = self.run_shell(body, env)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, 'https://x-access-token:github_pat_abc123@github.com/example/repo.git')


if __name__ == '__main__':
    unittest.main()

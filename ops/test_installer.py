"""Exercise installer control flow without installing packages or changing a host."""
import json
import os
import pty
from pathlib import Path
import subprocess
import tempfile
import unittest

from test_deployment import function


SCRIPT = Path(__file__).with_name('install-ubuntu.sh').read_text()
# Keep the actual entrypoint, traps, logging and completion/failure messages.
DEFINITIONS = SCRIPT.rsplit('\nmain "$@"', 1)[0]


class InstallerTests(unittest.TestCase):
    def run_shell(self, body, env=None):
        return subprocess.run(['bash', '-c', 'set -Eeuo pipefail\n' + body],
                              capture_output=True, text=True, env={**os.environ, **(env or {})})

    def run_installer(self, directory, *, failure='', verbose=False, localhost=False):
        mocks = '''
TRUSTED_TMP=""
ENV_FILE="$TMPDIR/easysrt.env"
PRIMARY_IP=192.0.2.10
FRONTEND_PORT=8090
UPDATER_PORT=8091
PUBLIC_ORIGIN=http://192.0.2.10:8090
INSTALLING_USER=installer-test
OS_NAME=Ubuntu
OS_VERSION=24.04
EXISTING_RUNTIME_CONFIG=false
'''
        noops = ('detect_host assert_supported_ubuntu detect_primary_ip find_recommended_port '
                 'ensure_sudo ensure_node_runtime ensure_pnpm assert_python_version ensure_uv '
                 'ensure_user_and_group ensure_repo_token_if_needed clone_or_update_repo '
                 'install_backend install_frontend install_services health_check')
        mocks += '\n'.join(f'{name}() {{ :; }}' for name in noops.split())
        mocks += '''
apt_install_if_missing() { printf 'noisy package output\\n'; apt_update_done=1; }
prepare_privileged_source() { TRUSTED_COMMIT=abc123; }
sudo() { command "$@"; }
''' + function('install-ubuntu.sh', 'load_existing_runtime_config') + '''
configure_runtime() {
  load_existing_runtime_config
  [[ "$EXISTING_RUNTIME_CONFIG" == false ]]
  [[ "$apt_update_done" == 1 && "$TRUSTED_COMMIT" == abc123 ]]
  printf 'runtime prompts reached\\n'
}
'''
        if localhost:
            mocks += '\nFRONTEND_HOST=127.0.0.1\n'
        if failure == 'nested':
            # These commands must never reach the line after false, even though
            # run_logged and run_interactive wrap their caller functions.
            mocks += '\ninner_failure() { false; echo WRONG_CONTINUED; }\ninstall_frontend() { inner_failure; echo WRONG_CONTINUED; }\n'
        elif failure == 'config':
            mocks += '\nconfigure_runtime() { die "Invalid frontend port"; }\n'
        elif failure == 'health':
            mocks += '\nhealth_check() { die "Backend health check failed"; }\n'
        elif failure == 'exit':
            mocks += '\ninstall_backend() { exit 23; }\n'
        elif failure == 'cancel':
            mocks += '\ninstall_backend() { kill -INT "$$"; }\n'
        result = self.run_shell(DEFINITIONS + mocks + '\nmain',
                                {'TMPDIR': directory, 'EASYSRT_VERBOSE': '1' if verbose else '0'})
        logs = list(Path(directory).glob('easysrt-install.*.log'))
        self.assertEqual(len(logs), 1, result.stderr)
        self.assertEqual(logs[0].stat().st_mode & 0o777, 0o600)
        return result, logs[0].read_text()

    def test_fresh_install_gets_past_step_six_and_prints_browser_url(self):
        with tempfile.TemporaryDirectory() as directory:
            result, log = self.run_installer(directory)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('[11/11]', result.stdout)
            self.assertIn('EasySRT is ready.', result.stdout)
            self.assertIn('Open in your browser: http://192.0.2.10:8090', result.stdout)
            self.assertIn('Create your first owner account', result.stdout)
            self.assertIn('Commit: abc123', result.stdout)
            self.assertNotIn('noisy package output', result.stdout)
            self.assertIn('noisy package output', log)
            self.assertIn('runtime prompts reached', log)
            self.assertNotIn('did not complete', result.stderr)

    def test_nested_errors_stop_immediately_in_both_output_modes(self):
        for verbose in (False, True):
            with self.subTest(verbose=verbose), tempfile.TemporaryDirectory() as directory:
                result, log = self.run_installer(directory, failure='nested', verbose=verbose)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertNotIn('WRONG_CONTINUED', result.stdout + log)
                self.assertNotIn('[9/11]', result.stdout)
                self.assertNotIn('EasySRT is ready.', result.stdout)
                self.assertIn('step 8/11', result.stderr)
                self.assertIn('Installer line', log)
                self.assertIn('tail -n 60', result.stderr)
                self.assertIn('rerun the same installer command', result.stderr)

    def test_explicit_config_failure_is_actionable_and_logged(self):
        with tempfile.TemporaryDirectory() as directory:
            result, log = self.run_installer(directory, failure='config')
            self.assertEqual(result.returncode, 1)
            self.assertIn('step 6/11', result.stderr)
            self.assertIn('Reason: Invalid frontend port', result.stderr)
            self.assertIn('Invalid frontend port', log)
            self.assertNotIn('EasySRT is ready.', result.stdout)

    def test_health_failure_prints_service_recovery_and_never_success(self):
        with tempfile.TemporaryDirectory() as directory:
            result, log = self.run_installer(directory, failure='health')
            self.assertEqual(result.returncode, 1)
            self.assertIn('Backend health check failed', result.stderr + log)
            self.assertIn('step 11/11', result.stderr)
            self.assertIn('sudo journalctl', result.stderr)
            self.assertNotIn('EasySRT is ready.', result.stdout)

    def test_exit_and_interrupt_preserve_exit_status(self):
        for failure, code in [('exit', 23), ('cancel', 130)]:
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                result, _ = self.run_installer(directory, failure=failure)
                self.assertEqual(result.returncode, code, result.stderr)
                self.assertIn('did not complete', result.stderr)
                self.assertNotIn('EasySRT is ready.', result.stdout)

    def test_verbose_mode_streams_and_logs_package_output(self):
        with tempfile.TemporaryDirectory() as directory:
            result, log = self.run_installer(directory, verbose=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('noisy package output', result.stdout)
            self.assertIn('noisy package output', log)

    def test_localhost_instructions_include_frontend_and_updater_tunnel(self):
        with tempfile.TemporaryDirectory() as directory:
            result, _ = self.run_installer(directory, localhost=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('ssh -N -L 8090:127.0.0.1:8090 -L 8091:127.0.0.1:8091 installer-test@192.0.2.10', result.stdout)
            self.assertIn('Then open: http://localhost:8090', result.stdout)
            self.assertNotIn('Open in your browser: http://192.0.2.10', result.stdout)

    def test_existing_settings_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory, 'easysrt.env')
            config.write_text('EASYSRT_FRONTEND_PORT=8090\nEASYSRT_FRONTEND_HOST=127.0.0.1\n'
                              'EASYSRT_BACKEND_HOST=127.0.0.1\nEASYSRT_BACKEND_PORT=8092\n'
                              'EASYSRT_UPDATER_PORT=8091\nEASYSRT_FRONTEND_ORIGIN=http://localhost:8090\n')
            body = '''
sudo() { command "$@"; }
PUBLIC_ORIGIN=""
''' + function('install-ubuntu.sh', 'read_runtime_env_value') + function('install-ubuntu.sh', 'load_existing_runtime_config') + '''
load_existing_runtime_config
[[ "$EXISTING_RUNTIME_CONFIG" == true ]]
[[ "$FRONTEND_PORT" == 8090 && "$FRONTEND_HOST" == 127.0.0.1 ]]
[[ "$BACKEND_PORT" == 8092 && "$UPDATER_PORT" == 8091 ]]
[[ "$PUBLIC_ORIGIN" == http://localhost:8090 ]]
PUBLIC_ORIGIN=https://example.test
load_existing_runtime_config
[[ "$PUBLIC_ORIGIN" == https://example.test ]]
'''
            result = self.run_shell(body, {'ENV_FILE': str(config)})
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_ip_falls_back_when_no_default_route(self):
        body = '''
PRIMARY_IP=127.0.0.1
ip() { return 2; }
hostname() { echo 192.0.2.12; }
''' + function('install-ubuntu.sh', 'detect_primary_ip') + '''
detect_primary_ip
[[ "$PRIMARY_IP" == 192.0.2.12 ]]
hostname() { return 1; }
detect_primary_ip
[[ "$PRIMARY_IP" == 192.0.2.12 ]]
'''
        result = self.run_shell(body)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_real_runtime_configuration_creates_files_and_survives_retry(self):
        for host in ('0.0.0.0', '127.0.0.1'):
            with self.subTest(host=host):
                self.check_runtime_configuration(host)

    def check_runtime_configuration(self, host):
        with tempfile.TemporaryDirectory() as directory:
            # Sandbox direct shell file tests as well as sudo commands, even
            # when the machine already has a real EasySRT installation.
            definitions = DEFINITIONS.replace('/var/lib/justso-easysrt-updates', directory + '/updates')
            body = definitions + r"""
CONFIG_DIR="$TMPDIR/config"
ENV_FILE="$CONFIG_DIR/easysrt.env"
BACKEND_DIR="$TMPDIR/backend"
mkdir -p "$BACKEND_DIR"
# A retry preserves an existing LAN binding; fresh installs default to local.
if [[ "$TEST_FRONTEND_HOST" == 0.0.0.0 ]]; then
  mkdir -p "$CONFIG_DIR"
  printf 'EASYSRT_FRONTEND_HOST=0.0.0.0\nEASYSRT_FRONTEND_PORT=8090\n' > "$ENV_FILE"
fi
PRIMARY_IP=192.0.2.10
FRONTEND_HOST="$TEST_FRONTEND_HOST"
INSTALLING_USER=test-user
sudo() {
  if [[ "$1" == -u ]]; then shift 2; fi
  local arg
  local -a args=()
  for arg in "$@"; do
    args+=("${arg//\/var\/lib\/justso-easysrt-updates/$TMPDIR/updates}")
  done
  set -- "${args[@]}"
  case "$1" in
    chown|chmod) return 0 ;;
    install) mkdir -p "${@: -1}"; return ;;
  esac
  command "$@"
}
find_recommended_port() { RECOMMENDED_FRONTEND_PORT=8090; }
detect_primary_ip() { :; }
list_ip_addresses() { echo 192.0.2.10; }
port_is_free() { return 0; }
init_logging
run_interactive configure_runtime
secret_before="$(read_runtime_env_value EASYSRT_SECRET_KEY)"
[[ -n "$secret_before" && "$FRONTEND_PORT" == 8090 ]]
printf 'retry-marker' > "$BACKEND_DIR/data/app_config.json"
run_interactive configure_runtime
[[ "$EXISTING_RUNTIME_CONFIG" == true ]]
[[ "$(read_runtime_env_value EASYSRT_SECRET_KEY)" == "$secret_before" ]]
[[ "$(cat "$BACKEND_DIR/data/app_config.json")" == retry-marker ]]
INSTALL_SUCCEEDED=true
"""
            result = self.run_shell(body, {'TMPDIR': directory, 'TEST_FRONTEND_HOST': host})
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout + '\n'.join(p.read_text() for p in Path(directory).glob('*.log')))
            config = Path(directory, 'config/easysrt.env').read_text()
            self.assertIn('EASYSRT_FRONTEND_PORT=8090', config)
            origin_host = 'localhost' if host == '127.0.0.1' else '192.0.2.10'
            self.assertIn(f'EASYSRT_FRONTEND_ORIGIN=http://{origin_host}:8090', config)
            self.assertTrue(Path(directory, 'updates/update-job.json').exists())
            policy = json.loads(Path(directory, 'config/update-policy.json').read_text())
            self.assertEqual(policy['repo_ref'], 'main')

    def test_prompt_still_reads_from_terminal_when_logged(self):
        with tempfile.TemporaryDirectory() as directory:
            body = DEFINITIONS + r"""
init_logging
ask() { selected="$(prompt_with_default 'Frontend port' 5173)"; }
run_interactive ask
[[ "$selected" == 8090 ]]
INSTALL_SUCCEEDED=true
"""
            master, slave = pty.openpty()
            try:
                process = subprocess.Popen(['bash', '-c', body], stdin=slave,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                    env={**os.environ, 'TMPDIR': directory})
                os.close(slave)
                slave = None
                os.write(master, b'8090\n')
                stdout, stderr = process.communicate(timeout=10)
                self.assertEqual(process.returncode, 0, stderr)
                self.assertIn('Frontend port [5173]:', stdout)
            finally:
                os.close(master)
                if slave is not None:
                    os.close(slave)

    def test_yes_no_prompts_show_defaults_accept_words_and_retry_invalid_input(self):
        cases = [('y', '\n', 'yes', 'Y/n'), ('n', '\n', 'no', 'y/N'),
                 ('y', 'no\n', 'no', 'Y/n'), ('n', 'YES\n', 'yes', 'y/N'),
                 ('y', 'maybe\nyes\n', 'yes', 'Y/n')]
        for default, answer, expected, label in cases:
            with self.subTest(answer=answer, default=default), tempfile.TemporaryDirectory() as directory:
                body = DEFINITIONS + f"""
init_logging
if prompt_yes_no_default 'Keep access local?' {default}; then selected=yes; else selected=no; fi
printf 'selected=%s\\n' "$selected"
INSTALL_SUCCEEDED=true
"""
                master, slave = pty.openpty()
                try:
                    process = subprocess.Popen(['bash', '-c', body], stdin=slave,
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                        env={**os.environ, 'TMPDIR': directory})
                    os.close(slave)
                    slave = None
                    os.write(master, answer.encode())
                    stdout, stderr = process.communicate(timeout=10)
                    self.assertEqual(process.returncode, 0, stderr)
                    self.assertIn(f'Keep access local? [{label}]:', stderr)
                    self.assertIn(f'selected={expected}', stdout)
                    if 'maybe' in answer:
                        self.assertIn('Please answer yes or no.', stderr)
                finally:
                    os.close(master)
                    if slave is not None:
                        os.close(slave)

    def test_progress_reports_activity_and_cleans_up(self):
        # Use a fast heartbeat in this fixture; production reports every 15s.
        definitions = DEFINITIONS.replace('report_interval = 15', 'report_interval = 0.05')
        with tempfile.TemporaryDirectory() as directory:
            body = definitions + r"""
init_logging
STEP_TITLE=long-test-step
run_logged sleep 0.5
[[ -z "$PROGRESS_PID" ]]
INSTALL_SUCCEEDED=true
"""
            result = self.run_shell(body, {'TMPDIR': directory})
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('Still working: long-test-step', result.stdout)

    def test_cleanup_failure_does_not_mask_original_status(self):
        body = '''
exec 3>&1 4>&2
PROGRESS_PID=""
PROGRESS_FLAG=""
INSTALL_SUCCEEDED=true
TRUSTED_TMP=/unused-test-path
sudo() { return 7; }
''' + function('install-ubuntu.sh', 'stop_progress') + function('install-ubuntu.sh', 'on_exit') + '\ntrap on_exit EXIT\nexit 23\n'
        result = self.run_shell(body)
        self.assertEqual(result.returncode, 23)
        self.assertIn('Could not remove temporary source', result.stderr)


if __name__ == '__main__':
    unittest.main()

"""Garde-fous sur les workflows GitHub Actions.

Un workflow ne se teste pas en local : la seule façon de savoir qu'il est
cassé est de le voir échouer sur une vraie fusion — ou pire, de le voir
déployer sans avoir vérifié quoi que ce soit. Ces tests figent donc ce qui ne
doit jamais changer par inadvertance : les tests avant le déploiement, une
seule mise en production à la fois, l'empreinte du serveur vérifiée, et aucun
secret affiché.
"""

from pathlib import Path

WORKFLOWS = Path(__file__).resolve().parent.parent / ".github" / "workflows"


def _instructions(name: str) -> str:
    """Le workflow sans ses commentaires.

    Les commentaires de ces fichiers citent justement ce qu'on interdit
    (« jamais de StrictHostKeyChecking=no ») : les laisser ferait passer un
    test pour une raison qui n'a rien à voir avec ce que fait le workflow.
    """
    lines = (line.split("#", 1)[0] for line in (WORKFLOWS / name).read_text(encoding="utf-8").splitlines())
    return "\n".join(lines)


TESTS_WORKFLOW = _instructions("tests.yml")
DEPLOY_WORKFLOW = _instructions("deploy.yml")

SECRETS = ("ORACLE_HOST", "ORACLE_SSH_KEY", "ORACLE_KNOWN_HOSTS")


def test_tests_workflow_runs_pytest_on_pull_requests_and_master():
    assert "pull_request:" in TESTS_WORKFLOW
    assert "branches: [master]" in TESTS_WORKFLOW
    assert "python -m pytest -q" in TESTS_WORKFLOW


def test_tests_workflow_uses_the_python_of_the_server():
    """3.12 comme le VPS : une syntaxe incompatible doit échouer ici."""
    assert 'python-version: "3.12"' in TESTS_WORKFLOW


def test_tests_workflow_is_callable_by_the_deployment():
    assert "workflow_call:" in TESTS_WORKFLOW


def test_deploy_runs_on_master_and_on_demand():
    assert "branches: [master]" in DEPLOY_WORKFLOW
    assert "workflow_dispatch:" in DEPLOY_WORKFLOW


def test_deploy_waits_for_the_tests():
    assert "uses: ./.github/workflows/tests.yml" in DEPLOY_WORKFLOW
    assert "needs: tests" in DEPLOY_WORKFLOW


def test_only_one_deployment_at_a_time():
    """Deux `git reset --hard` + `pm2 restart` simultanés laisseraient le VPS
    dans un état indéterminé, et les déploiements en attente ne doivent pas
    être annulés : le dernier commit doit toujours partir."""
    assert "concurrency:" in DEPLOY_WORKFLOW
    assert "group: deploiement-vps" in DEPLOY_WORKFLOW
    assert "cancel-in-progress: false" in DEPLOY_WORKFLOW


def test_server_fingerprint_is_always_verified():
    assert "StrictHostKeyChecking=no" not in DEPLOY_WORKFLOW
    assert "StrictHostKeyChecking=yes" in DEPLOY_WORKFLOW
    assert "UserKnownHostsFile=" in DEPLOY_WORKFLOW


def test_missing_secrets_stop_the_deployment_without_failing():
    """Sans secrets, un job rouge à chaque fusion masquerait les vraies pannes."""
    for secret in SECRETS:
        assert f'secrets.{secret} }}}}' in DEPLOY_WORKFLOW
        assert f'-z "${secret}"' in DEPLOY_WORKFLOW
    assert "::warning::" in DEPLOY_WORKFLOW
    assert "steps.secrets.outputs.ready == 'true'" in DEPLOY_WORKFLOW


def test_no_secret_is_printed():
    """Les secrets ne transitent que par des variables d'environnement, jamais
    par un `echo`, un `cat` ou un `set -x` qui les recopierait dans les logs."""
    assert "set -x" not in DEPLOY_WORKFLOW
    for secret in SECRETS:
        assert f'echo "${secret}"' not in DEPLOY_WORKFLOW
        assert f"echo ${secret}" not in DEPLOY_WORKFLOW
    assert "cat $HOME/.ssh/sona_deploy" not in DEPLOY_WORKFLOW
    assert 'cat "$HOME/.ssh/sona_deploy"' not in DEPLOY_WORKFLOW


def test_the_private_key_is_removed_from_the_runner():
    assert 'rm -f "$HOME/.ssh/sona_deploy"' in DEPLOY_WORKFLOW
    assert "if: always()" in DEPLOY_WORKFLOW


def test_deployment_doc_lists_the_one_time_setup():
    doc = (Path(__file__).resolve().parent.parent / "docs" / "DEPLOIEMENT.md").read_text(encoding="utf-8")
    assert "ssh-keygen -t ed25519" in doc
    assert 'command="cd ~/sona && ./deploy.sh"' in doc
    assert "no-port-forwarding" in doc and "no-pty" in doc
    assert "ssh-keyscan" in doc
    for secret in SECRETS:
        assert secret in doc

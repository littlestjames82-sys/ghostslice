"""Port allocation and env copy: the other two jobs in the scope."""
import pytest

from tests.helpers import (cleanup_worktree, cli_available, combined,
                     create_worktree, make_repo, worktree_port)

pytestmark = pytest.mark.skipif(
    not cli_available(),
    reason="ghostworktree core not landed yet (see REPORT_B.md)")


def test_each_worktree_gets_a_port(tmp_path):
    repo = make_repo(tmp_path)
    proc, wt = create_worktree(repo, "port-task")
    assert wt is not None
    port = worktree_port(repo, wt, proc)
    if port is None:
        pytest.skip("core does not surface a port in output, state, or "
                    ".env; port visibility assumption in REPORT_B.md")
    assert 0 < port < 65536
    cleanup_worktree(repo, "port-task", wt, force=True)


def test_duplicate_port_allocation_is_not_silently_shared(tmp_path):
    """Adversarial: two worktrees must never both claim the same port.

    If the core accepts an explicit --port, the second create with
    the same port must fail or be reassigned. If it does not accept
    an explicit port, two auto-allocated worktrees must still differ.
    """
    repo = make_repo(tmp_path)
    proc1, wt1 = create_worktree(repo, "port-one", port=18741)
    if wt1 is None:
        pytest.skip("explicit --port create form not supported by core")
    port1 = worktree_port(repo, wt1, proc1) or 18741
    proc2, wt2 = create_worktree(repo, "port-two", port=18741)
    if wt2 is not None:
        port2 = worktree_port(repo, wt2, proc2)
        assert port2 != port1, (
            f"two live worktrees both claim port {port1}\n"
            + combined(proc2))
    # wt2 is None (second create refused) is also a correct outcome.
    cleanup_worktree(repo, "port-one", wt1, force=True)
    if wt2 is not None:
        cleanup_worktree(repo, "port-two", wt2, force=True)


def test_two_auto_worktrees_get_different_ports(tmp_path):
    repo = make_repo(tmp_path)
    proc1, wt1 = create_worktree(repo, "auto-one")
    proc2, wt2 = create_worktree(repo, "auto-two")
    assert wt1 is not None and wt2 is not None
    port1 = worktree_port(repo, wt1, proc1)
    port2 = worktree_port(repo, wt2, proc2)
    if port1 is None or port2 is None:
        pytest.skip("core does not surface ports; see REPORT_B.md")
    assert port1 != port2
    cleanup_worktree(repo, "auto-one", wt1, force=True)
    cleanup_worktree(repo, "auto-two", wt2, force=True)


def test_env_is_copied_into_the_worktree(tmp_path):
    repo = make_repo(tmp_path)
    _, wt = create_worktree(repo, "env-task")
    assert wt is not None
    env_file = wt / ".env"
    example_file = wt / ".env.example"
    present = ""
    if env_file.exists():
        present = env_file.read_text()
    elif example_file.exists():
        present = example_file.read_text()
    assert present, "worktree has neither .env nor .env.example copied in"
    # At least the variable NAMES from the source env must be there.
    # (Values may legitimately come from .env or from .env.example.)
    assert "APP_NAME" in present
    cleanup_worktree(repo, "env-task", wt, force=True)


def test_real_env_secret_marker_appears_nowhere(tmp_path):
    """PLAN verification bar, adversarial: the real .env is never read.

    The fixture repo's real .env carries SECRET_MARKER as a value.
    It must appear in no file inside the created worktree, in no
    registry record, and in no CLI output. Only .env.example (which
    does not contain it) may be copied / used to seed the worktree .env.
    """
    from tests.helpers import SECRET_MARKER, registry_path
    repo = make_repo(tmp_path)
    assert SECRET_MARKER in (repo / ".env").read_text()
    assert SECRET_MARKER not in (repo / ".env.example").read_text()
    proc, wt = create_worktree(repo, "secret-task")
    assert wt is not None
    assert SECRET_MARKER not in combined(proc)
    for path in wt.rglob("*"):
        if path.is_file() and ".git" not in path.parts:
            assert SECRET_MARKER not in path.read_text(
                encoding="utf-8", errors="replace"), (
                f"real .env value leaked into worktree file {path}")
    reg = registry_path(repo)
    if reg.exists():
        assert SECRET_MARKER not in reg.read_text()
    cleanup_worktree(repo, "secret-task", wt, force=True)


def test_env_copy_does_not_modify_the_source_env(tmp_path):
    repo = make_repo(tmp_path)
    before = (repo / ".env").read_text()
    _, wt = create_worktree(repo, "env-source-task")
    assert wt is not None
    assert (repo / ".env").read_text() == before
    cleanup_worktree(repo, "env-source-task", wt, force=True)

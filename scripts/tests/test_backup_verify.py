"""Backup verification (task #7182): the weekly verify was BLIND, not the backups broken.

1. `git bundle verify` ran with no repository (cron's cwd), so it failed for every bundle, every Sunday. Bundles must be verified inside
   their OWN source repo, found by the same repo list the creator uses (lib_common.sh gitbundle_repos: one definition, two callers).
2. The config sentinel was appended with `tar -rzf` to a COMPRESSED archive, which GNU tar cannot do (`|| true` hid it), so the archive
   never held .backup_sentinel and the encryption roundtrip failed every week. It is now written into the single-pass archive.

These run the REAL scripts in a sandbox (temp ARCHIE_REPO / BACKUP_ROOT / GITBUNDLE_ROOT). psql_archie is `docker exec archie_database psql`,
so an unguarded run WRITES ROWS INTO THE PRODUCTION backup_log (it did, once: ids 9670-9676, deleted). Two independent guards: `docker` is an
EXPORTED SHELL FUNCTION (a PATH shim does not work: lib_common.sh resets PATH), and DOCKER_HOST points at a socket that does not exist, so
even a bypassed shim cannot reach the daemon.
"""

import os
import subprocess
import tarfile
from pathlib import Path

import pytest

BACKUP = Path(__file__).resolve().parents[2] / "scripts" / "backup"
LIB = BACKUP / "lib_common.sh"


@pytest.fixture
def sandbox(tmp_path):
    root = tmp_path / "repo_root"
    root.mkdir()
    env = {
        "PATH": os.environ["PATH"],
        "DOCKER_HOST": "unix:///nonexistent/docker.sock",  # guard 2: the real daemon is unreachable
        "HOME": str(tmp_path),
        "SHIM_LOG": str(tmp_path / "shim.log"),
        "BACKUP_ROOT": str(tmp_path / "backups"),
        "BACKUP_LOG_FILE": str(tmp_path / "backup.log"),
        "ARCHIE_REPO": str(root),
        "GITBUNDLE_ROOT": str(root),
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
    }
    (tmp_path / "backups").mkdir()
    return tmp_path, root, env


SHIM = 'docker() { cat >/dev/null 2>&1; echo "$*" >> "$SHIM_LOG"; return 0; }; export -f docker; '  # guard 1


def bash(script, env, cwd="/"):
    return subprocess.run(["bash", "-c", SHIM + script], env=env, cwd=cwd, capture_output=True, text=True)


def mkrepo(path: Path, commits=2):
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    for i in range(commits):
        (path / f"f{i}.txt").write_text(f"{i}\n")
        subprocess.run(["git", "-C", str(path), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(path), "-c", "commit.gpgsign=false", "commit", "-qm", f"c{i}"], check=True)
    return path


def mkbundle(repo: Path, dest: Path, name):
    out = dest / f"{name}_incremental_20261012_061620.bundle"
    subprocess.run(["git", "-C", str(repo), "bundle", "create", str(out), "--all"], check=True, capture_output=True)
    return out


# --- repo discovery: ONE definition, used by both the creator and the verifier ------------------------------------------------------------


def test_gitbundle_repos_lists_the_root_then_every_git_subdir_with_normalised_names(sandbox):
    _, root, env = sandbox
    mkrepo(root / "kytran-business-suite")
    mkrepo(root / "archie-code")
    (root / "plain_dir").mkdir()  # no .git: not a repo
    r = bash(f"source {LIB}; gitbundle_repos", env)
    lines = r.stdout.splitlines()
    assert lines[0] == f"archie_brain:{root}"
    assert f"kytran_business_suite:{root}/kytran-business-suite" in lines and f"archie_code:{root}/archie-code" in lines
    assert not any("plain_dir" in x for x in lines)


def test_the_creator_builds_its_repo_list_from_the_shared_function_not_its_own_copy():
    src = (BACKUP / "component_gitbundle.sh").read_text()
    assert "mapfile -t REPOS < <(gitbundle_repos)" in src and "REPOS=(" not in src


# --- the bundle verifier ----------------------------------------------------------------------------------------------------------------


def test_verify_gitbundle_passes_from_any_cwd_for_a_healthy_bundle(sandbox):
    tmp, root, env = sandbox
    repo = mkrepo(root / "proj-a")
    b = mkbundle(repo, tmp / "backups", "proj_a")
    for cwd in ("/", str(tmp), str(repo)):  # cron's cwd was /home/kytran: it must not matter
        assert bash(f"source {LIB}; verify_gitbundle {b}", env, cwd=cwd).returncode == 0, cwd


def test_the_old_call_fails_outside_a_repo_which_is_why_the_weekly_verify_was_blind(sandbox):
    tmp, root, env = sandbox
    b = mkbundle(mkrepo(root / "proj-a"), tmp / "backups", "proj_a")
    old = subprocess.run(["git", "bundle", "verify", str(b)], cwd="/", capture_output=True, text=True)
    assert old.returncode != 0 and "repository" in old.stderr.lower()  # the exact failure from the task


def test_verify_gitbundle_fails_on_a_corrupt_bundle(sandbox):
    tmp, root, env = sandbox
    b = mkbundle(mkrepo(root / "proj-a"), tmp / "backups", "proj_a")
    data = bytearray(b.read_bytes())
    data[len(data) // 2] ^= 0xFF
    b.write_bytes(bytes(data[: len(data) - 40]))  # damaged and truncated
    assert bash(f"source {LIB}; verify_gitbundle {b}", env).returncode == 1


def test_verify_gitbundle_reports_unverifiable_as_2_or_3_never_as_corruption(sandbox):
    tmp, root, env = sandbox
    b = mkbundle(mkrepo(root / "proj-a"), tmp / "backups", "proj_a")
    gone = tmp / "backups" / "removed_repo_incremental_20261012_061620.bundle"
    gone.write_bytes(b.read_bytes())
    assert bash(f"source {LIB}; verify_gitbundle {gone}", env).returncode == 3  # no such source repo
    weird = tmp / "backups" / "not-a-bundle-name.bundle"
    weird.write_bytes(b.read_bytes())
    assert (
        bash(f"source {LIB}; verify_gitbundle {weird}", env).returncode == 2
    )  # name does not carry <repo>_<kind>_<ts>


def test_an_incremental_bundle_is_verified_against_its_own_repo_not_a_neighbour(sandbox):
    """A FULL bundle carries all its history (no prerequisites) so it verifies anywhere; an INCREMENTAL one needs its own repo's earlier
    commits, which is exactly the task's 'Repository lacks these prerequisite commits' from a cross-repo check."""
    tmp, root, env = sandbox
    a = mkrepo(root / "proj-a", commits=3)
    mkrepo(root / "proj-b", commits=1)
    base = subprocess.run(["git", "-C", str(a), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    (a / "later.txt").write_text("x\n")
    subprocess.run(["git", "-C", str(a), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(a), "-c", "commit.gpgsign=false", "commit", "-qm", "later"], check=True)
    ba = tmp / "backups" / "proj_a_incremental_20261012_061620.bundle"
    subprocess.run(["git", "-C", str(a), "bundle", "create", str(ba), f"{base}..HEAD"], check=True, capture_output=True)
    assert bash(f"source {LIB}; verify_gitbundle {ba}", env).returncode == 0
    mis = tmp / "backups" / "proj_b_incremental_20261012_061620.bundle"  # proj_a's increment filed under proj_b's name
    mis.write_bytes(ba.read_bytes())
    assert bash(f"source {LIB}; verify_gitbundle {mis}", env).returncode == 1


def test_a_hyphenated_repo_name_maps_back_through_its_underscored_bundle_name(sandbox):
    tmp, root, env = sandbox
    b = mkbundle(mkrepo(root / "kytran-business-suite"), tmp / "backups", "kytran_business_suite")
    assert bash(f"source {LIB}; verify_gitbundle {b}", env).returncode == 0


# --- the whole verify script, bundle section ---------------------------------------------------------------------------------------------


def run_verify(env, cwd="/"):
    (Path(env["ARCHIE_REPO"]) / ".env").write_text("BACKUP_CONFIG_PASSPHRASE=\n")
    return subprocess.run(
        ["bash", "-c", SHIM + f"exec bash {BACKUP / 'verify_backups.sh'}"],
        env=env,
        cwd=cwd,
        capture_output=True,
        text=True,
    )


def test_verify_script_logs_ok_for_healthy_bundles_and_no_longer_fails_them(sandbox):
    tmp, root, env = sandbox
    mkbundle(mkrepo(root / "proj-a"), tmp / "backups", "proj_a")
    r = run_verify(env)
    log = Path(env["BACKUP_LOG_FILE"]).read_text()
    assert "verify OK: gitbundle" in log and "verify FAIL: gitbundle" not in log, log
    assert r.returncode == 0, r.stderr[-400:]


def test_verify_script_fails_the_run_on_a_corrupt_bundle_and_only_warns_on_an_unverifiable_one(sandbox):
    tmp, root, env = sandbox
    good = mkbundle(mkrepo(root / "proj-a"), tmp / "backups", "proj_a")
    bad = tmp / "backups" / "proj_a_full_20261012_061620.bundle"
    bad.write_bytes(good.read_bytes()[:200])
    assert run_verify(env).returncode == 1
    assert "verify FAIL: gitbundle" in Path(env["BACKUP_LOG_FILE"]).read_text()
    bad.unlink()
    orphan = tmp / "backups" / "gone_repo_incremental_20261012_061621.bundle"
    orphan.write_bytes(good.read_bytes())
    Path(env["BACKUP_LOG_FILE"]).write_text("")
    r = run_verify(env)
    log = Path(env["BACKUP_LOG_FILE"]).read_text()
    assert "verify SKIP: gitbundle" in log and "verify FAIL: gitbundle" not in log and r.returncode == 0


def test_the_shim_not_the_production_database_received_the_summary_row(sandbox):
    tmp, root, env = sandbox
    mkbundle(mkrepo(root / "proj-a"), tmp / "backups", "proj_a")
    run_verify(env)
    assert "archie_database" in Path(env["SHIM_LOG"]).read_text()  # psql_archie went to the fake docker


# --- the config archive -----------------------------------------------------------------------------------------------------------------


def _run_config(sandbox):
    tmp, root, env = sandbox
    (root / ".env").write_text("BACKUP_CONFIG_PASSPHRASE=test-pass-phrase\nOTHER=1\n")
    (root / "docker-compose.yml").write_text("services: {}\n")
    (root / ".mcp.json").write_text("{}\n")
    (root / "CLAUDE.md").write_text("# c\n")
    (root / ".claude" / "rules").mkdir(parents=True)
    (root / ".claude" / "rules" / "x.md").write_text("rule\n")
    (root / "nginx").mkdir()
    (root / "nginx" / "n.conf").write_text("n\n")
    (root / "secrets").mkdir()
    (root / "secrets" / "s.txt").write_text("s\n")
    run = tmp / "run"
    run.mkdir()
    r = subprocess.run(
        ["bash", "-c", SHIM + f"exec bash {BACKUP / 'component_config.sh'} {run}"],
        env=env,
        capture_output=True,
        text=True,
    )
    return r, run, env


def test_the_config_archive_contains_the_sentinel_and_survives_the_roundtrip(sandbox, tmp_path):
    r, run, env = _run_config(sandbox)
    assert r.returncode == 0, r.stderr[-500:]
    enc = next((run / "config").glob("config_*.tar.gz.enc"))
    plain = tmp_path / "c.tar.gz"
    subprocess.run(
        [
            "openssl",
            "enc",
            "-d",
            "-aes-256-cbc",
            "-pbkdf2",
            "-iter",
            "200000",
            "-in",
            str(enc),
            "-out",
            str(plain),
            "-pass",
            "pass:test-pass-phrase",
        ],
        check=True,
        capture_output=True,
    )
    with tarfile.open(plain) as t:
        names = t.getnames()
        assert ".backup_sentinel" in names, names  # the whole point: it was MISSING before
        assert t.extractfile(".backup_sentinel").read().decode().startswith("archie-backup-sentinel")
    assert {".env", "docker-compose.yml", "CLAUDE.md", "nginx/n.conf", "secrets/s.txt", ".claude/rules/x.md"} <= set(
        names
    )


def test_no_tar_append_to_a_compressed_archive_remains_and_no_error_is_swallowed():
    src = (BACKUP / "component_config.sh").read_text()
    code = "\n".join(line for line in src.splitlines() if not line.lstrip().startswith("#"))
    assert "tar -rzf" not in code and "tar -rf" not in code  # GNU tar cannot append to a .gz
    assert "|| true" not in code.split("tar --ignore-failed-read")[1].split("openssl")[0]


def test_the_config_run_logs_no_tar_update_error(sandbox):
    r, run, env = _run_config(sandbox)
    assert "Cannot update compressed archives" not in Path(env["BACKUP_LOG_FILE"]).read_text()


# --- the harness cannot reach production -----------------------------------------------------------------------------------------------


def test_the_harness_cannot_reach_the_real_docker_or_database(sandbox):
    _, _, env = sandbox
    assert (
        "function" in bash("source " + str(LIB) + "; type docker | head -1", env).stdout
    )  # guard 1 survives the lib's PATH reset
    real = subprocess.run(["docker", "ps"], env=env, capture_output=True, text=True)  # guard 2, with NO shim
    assert real.returncode != 0 and "nonexistent" in real.stderr


# --- git bundle verify alone is too weak: it never reads the pack -----------------------------------------------------------------------


def test_bundle_verify_alone_misses_a_damaged_pack_but_verify_gitbundle_catches_it(sandbox):
    tmp, root, env = sandbox
    repo = mkrepo(root / "proj-a", commits=6)
    b = mkbundle(repo, tmp / "backups", "proj_a")
    data = bytearray(b.read_bytes())
    data[len(data) - 60] ^= 0xFF  # flip a byte inside the pack
    b.write_bytes(bytes(data))
    header_only = subprocess.run(["git", "-C", str(repo), "bundle", "verify", str(b)], capture_output=True, text=True)
    assert header_only.returncode == 0, "if this starts failing, git got stricter and the extra pack check is redundant"
    assert bash(f"source {LIB}; verify_gitbundle {b}", env).returncode == 1


def test_verify_gitbundle_never_writes_into_the_live_repo(sandbox):
    tmp, root, env = sandbox
    repo = mkrepo(root / "proj-a", commits=4)
    b = mkbundle(repo, tmp / "backups", "proj_a")
    before = sorted(p.name for p in (repo / ".git" / "objects").rglob("*") if p.is_file())
    refs_before = subprocess.run(["git", "-C", str(repo), "for-each-ref"], capture_output=True, text=True).stdout
    assert bash(f"source {LIB}; verify_gitbundle {b}", env).returncode == 0
    assert sorted(p.name for p in (repo / ".git" / "objects").rglob("*") if p.is_file()) == before
    assert (
        subprocess.run(["git", "-C", str(repo), "for-each-ref"], capture_output=True, text=True).stdout == refs_before
    )


def test_an_incremental_bundle_with_prerequisites_verifies_through_the_alternate_object_store(sandbox):
    tmp, root, env = sandbox
    repo = mkrepo(root / "proj-a", commits=3)
    base = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    for i in range(3, 6):
        (repo / f"g{i}.txt").write_text(f"{i}\n")
        subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(repo), "-c", "commit.gpgsign=false", "commit", "-qm", f"c{i}"], check=True)
    b = tmp / "backups" / "proj_a_incremental_20261012_061620.bundle"
    subprocess.run(
        ["git", "-C", str(repo), "bundle", "create", str(b), f"{base}..HEAD"], check=True, capture_output=True
    )  # has prerequisites
    assert bash(f"source {LIB}; verify_gitbundle {b}", env).returncode == 0


def test_the_nightly_triage_bundle_names_are_verified_not_skipped(sandbox):
    """backup_triage.sh (the cron producer) names bundles <name>_<ts>.bundle with 'kytran-' stripped and no kind. The first fix only
    parsed component_gitbundle.sh's names and skipped ALL FOUR real bundles on the first production run."""
    tmp, root, env = sandbox
    for repo_dir, bundle_name in (
        ("kytran-business-suite", "business-suite"),
        ("kytran-server-manager", "server-manager"),
        ("kytran-creed", "creed"),
    ):
        repo = mkrepo(root / repo_dir)
        out = tmp / "backups" / f"{bundle_name}_20261012_060001.bundle"
        subprocess.run(["git", "-C", str(repo), "bundle", "create", str(out), "--all"], check=True, capture_output=True)
        assert bash(f"source {LIB}; verify_gitbundle {out}", env).returncode == 0, bundle_name
    top = tmp / "backups" / "archie_brain_20261012_060001.bundle"
    mkrepo(root / "unused-sub")  # the root itself must be a repo for the platform bundle
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    (root / "r.txt").write_text("x")
    subprocess.run(["git", "-C", str(root), "add", "r.txt"], check=True)
    subprocess.run(["git", "-C", str(root), "-c", "commit.gpgsign=false", "commit", "-qm", "r"], check=True)
    subprocess.run(["git", "-C", str(root), "bundle", "create", str(top), "--all"], check=True, capture_output=True)
    assert bash(f"source {LIB}; verify_gitbundle {top}", env).returncode == 0


def test_a_corrupt_triage_named_bundle_fails_rather_than_skips(sandbox):
    tmp, root, env = sandbox
    repo = mkrepo(root / "kytran-creed")
    out = tmp / "backups" / "creed_20261012_060001.bundle"
    subprocess.run(["git", "-C", str(repo), "bundle", "create", str(out), "--all"], check=True, capture_output=True)
    data = bytearray(out.read_bytes())
    data[-40] ^= 0xFF
    out.write_bytes(bytes(data))
    assert bash(f"source {LIB}; verify_gitbundle {out}", env).returncode == 1


def test_the_pack_scratch_dir_is_on_the_backup_disk_not_tmp_and_is_cleaned_up(sandbox):
    """/tmp is a small tmpfs: a first version ran out of space unbundling the real 150 MB bundle and called it corrupt."""
    tmp, root, env = sandbox
    repo = mkrepo(root / "kytran-creed")
    out = tmp / "backups" / "creed_20261012_060001.bundle"
    subprocess.run(["git", "-C", str(repo), "bundle", "create", str(out), "--all"], check=True, capture_output=True)
    env = {**env, "TMPDIR": "/nonexistent/tmpdir"}  # if the scratch dir used TMPDIR/tmp, mktemp would fail -> rc 1
    assert bash(f"source {LIB}; verify_gitbundle {out}", env).returncode == 0
    assert not list((tmp / "backups").glob(".verify_pack.*")), "scratch directory was left behind"


def test_the_nightly_triage_config_archive_carries_the_sentinel_the_verifier_looks_for(tmp_path):
    """The archive the verifier decrypts is written by backup_triage.sh, not component_config.sh: it must hold .backup_sentinel too."""
    src = (Path(__file__).resolve().parents[2] / "scripts" / "backup_triage.sh").read_text()
    start = src.index("# ----- [4/4] Config tar")
    end = src.index('if [[ -n "${BACKUP_CONFIG_PASSPHRASE:-}" ]] && [[ -s')
    block = src[start:end].replace("/mnt/archie_brain", str(tmp_path / "root"))
    root = tmp_path / "root"
    (root / ".claude" / "rules").mkdir(parents=True)
    (root / ".env").write_text("X=1\n")
    run = tmp_path / "run"
    (run / "config").mkdir(parents=True)
    script = f'log() {{ :; }}\nRUN={run}\nTS=T1\nLOG={tmp_path / "l.log"}\n' + block
    r = subprocess.run(["bash", "-c", script], capture_output=True, text=True, env={"PATH": os.environ["PATH"]})
    assert r.returncode == 0, r.stderr
    archive = run / "config" / "config_T1.tar.gz"
    with tarfile.open(archive) as t:
        names = t.getnames()
        assert ".backup_sentinel" in names and ".env" in names, names
        first = t.extractfile(".backup_sentinel").read().decode().splitlines()[0]
    assert first.startswith("archie-backup-sentinel"), first
    assert not (run / "config" / ".sentinel_stage").exists(), "staging dir left behind"

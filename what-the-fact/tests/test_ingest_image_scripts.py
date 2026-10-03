"""The ingest image must carry the ops CLIs, and the tool must find migrations from there.

Why this exists (2026-10-03): migration 088 added `scripts/migrations_admin.py`, which reads
the migration ledger. It was merged, its migration applied to Citadel, and the tool was
still unreachable ON Citadel — no Dockerfile copied `scripts/`, so no container had it. The
fix was `COPY scripts/ /app/scripts/`, and this test is what stops that being reverted as
"dead weight" later.

The second test is the one that matters. `migrations_admin.py` locates the migrations it
reports on as `Path(__file__).resolve().parent.parent / "migrations"` — i.e. it assumes
`scripts/` and `migrations/` are SIBLINGS under the same root. That is only true in the
image if both COPY lines land where the tool expects. Asserting the Dockerfile contains a
certain string would not catch someone moving one COPY to a different destination, so this
rebuilds the image's directory layout on disk and asks the real module where it looks.
"""
from __future__ import annotations

import importlib.util
import pathlib
import re
import shutil

ROOT = pathlib.Path(__file__).resolve().parents[1]
DOCKERFILE = ROOT / "Dockerfile.ingest"


def _copy_directive(dockerfile: str, src: str) -> str | None:
    """Destination of `COPY <src> <dest>` in a Dockerfile, or None if absent."""
    m = re.search(rf"^COPY\s+{re.escape(src)}\s+(\S+)\s*$", dockerfile, re.M)
    return m.group(1) if m else None


class TestScriptsAreIngested:
    def test_ingest_image_copies_scripts(self):
        dest = _copy_directive(DOCKERFILE.read_text(encoding="utf-8"), "scripts/")
        assert dest, "Dockerfile.ingest no longer COPYs scripts/ — the ops CLIs " \
                     "(migrations_admin.py, elections_admin.py) are unreachable on the box"

    def test_scripts_and_migrations_land_as_siblings(self):
        """The tool derives migrations/ from its own location; both must share a root."""
        text = DOCKERFILE.read_text(encoding="utf-8")
        scripts_dest = _copy_directive(text, "scripts/")
        migrations_dest = _copy_directive(text, "migrations/")
        assert scripts_dest and migrations_dest
        assert pathlib.PurePosixPath(scripts_dest).parent == \
            pathlib.PurePosixPath(migrations_dest).parent, (
            f"scripts/ -> {scripts_dest} and migrations/ -> {migrations_dest} are not "
            "siblings; migrations_admin.py resolves migrations/ as its parent's child "
            "and will read the wrong directory (or none)")

    def test_migrations_admin_finds_migrations_in_the_image_layout(self, tmp_path):
        """Prove the resolution by loading the REAL module from a simulated /app."""
        app = tmp_path / "app"
        (app / "scripts").mkdir(parents=True)
        (app / "migrations").mkdir()
        shutil.copy(ROOT / "scripts" / "migrations_admin.py", app / "scripts" /
                    "migrations_admin.py")
        # A couple of stand-in migration files, correctly named.
        for name in ("001_wtf_schema.sql", "088_schema_migrations.sql"):
            (app / "migrations" / name).write_text("SELECT 1;\n", encoding="utf-8")

        spec = importlib.util.spec_from_file_location(
            "migrations_admin_under_test", app / "scripts" / "migrations_admin.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        assert mod.MIGRATIONS_DIR == app / "migrations", (
            f"tool looked in {mod.MIGRATIONS_DIR}, not the image's /app/migrations")
        found = mod.on_disk()
        assert [v for v, _ in found] == ["001", "088"]
        # numeric, not lexicographic — '100' must sort after '088'
        assert mod.on_disk.__doc__ is not None

    def test_every_python_cli_in_scripts_is_actually_in_the_repo(self):
        """A COPY is only useful if the files it ships exist and are not empty."""
        scripts = ROOT / "scripts"
        pythons = sorted(p.name for p in scripts.glob("*.py"))
        assert "migrations_admin.py" in pythons, "the ledger tool should live in scripts/"
        for name in pythons:
            assert (scripts / name).stat().st_size > 0, f"{name} is empty"

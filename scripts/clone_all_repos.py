#!/usr/bin/env python3
"""Clone all tracked GitHub repos to /mnt/archie_brain/repos/"""

import os
import subprocess
import psycopg2

REPOS_BASE = "/mnt/archie_brain/repos"


def db():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "archie_database"),
        database=os.getenv("DB_NAME", "archie"),
        user=os.getenv("DB_USER", "archie"),
        password=os.getenv("DB_PASSWORD"),
    )


conn = db()
cur = conn.cursor()
cur.execute("SELECT id, repo_name, repo_type FROM github_repositories ORDER BY id")
repos = cur.fetchall()
cur.close()
conn.close()

token = os.environ.get("GITHUB_TOKEN")
try:
    with open("/mnt/archie_brain/secrets/api/github_token.txt") as f:
        token = f.read().strip()
except:
    pass

ok = 0
fail = 0
for repo_id, rname, rtype in repos:
    name = rname.split("/")[1]
    lp = os.path.join(REPOS_BASE, rtype, name)
    act = "?"
    try:
        if os.path.isdir(os.path.join(lp, ".git")):
            r = subprocess.run(["git", "-C", lp, "pull", "--ff-only"], capture_output=True, text=True, timeout=120)
            act = "pulled" if r.returncode == 0 else "pull-err"
        else:
            os.makedirs(os.path.dirname(lp), exist_ok=True)
            url = (
                f"https://x-access-token:{token}@github.com/{rname}.git" if token else f"https://github.com/{rname}.git"
            )
            r = subprocess.run(["git", "clone", "--depth", "1", url, lp], capture_output=True, text=True, timeout=300)
            act = "cloned" if r.returncode == 0 else "clone-err"

        if r.returncode == 0:
            c2 = db()
            u = c2.cursor()
            u.execute(
                "UPDATE github_repositories SET local_path=%s, status='cloned', "
                "cloned_at=COALESCE(cloned_at, NOW()), updated_at=NOW() WHERE id=%s",
                (lp, repo_id),
            )
            c2.commit()
            u.close()
            c2.close()
            ok += 1
        else:
            fail += 1
            print(f"FAIL {rname}: {r.stderr[:120]}")
    except Exception as e:
        fail += 1
        print(f"ERR {rname}: {e}")

    print(f"{act}: {rname}")

print(f"\nDONE: {ok} ok, {fail} failed out of {len(repos)}")

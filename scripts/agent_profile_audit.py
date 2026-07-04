#!/usr/bin/env python3
"""Export agent identity data for audit review."""

import psycopg2
import csv
import os
import sys

DB_CONFIG = {
    "host": os.getenv("DB_HOST", "192.168.1.200"),
    "port": os.getenv("DB_PORT", "5432"),
    "dbname": os.getenv("DB_NAME", "archie"),
    "user": os.getenv("DB_USER", "archie"),
    "password": os.getenv("DB_PASSWORD", ""),
}


def audit_agents():
    conn = psycopg2.connect(**DB_CONFIG)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, name, display_name, department, floor, title,
                   gender, ethnicity, age_range, appearance_notes,
                   portrait_prompt, email, gmail, first_name, last_name,
                   bio, avatar_url,
                   CASE WHEN system_prompt IS NOT NULL AND system_prompt != '' THEN 'YES' ELSE 'MISSING' END as has_prompt,
                   CASE WHEN avatar_url IS NOT NULL AND avatar_url != '' THEN 'YES' ELSE 'MISSING' END as has_avatar,
                   is_department_ai
            FROM agents
            ORDER BY floor, department, display_name
        """
        )
        rows = cur.fetchall()
        cols = [desc[0] for desc in cur.description]

        with open("/tmp/agent_audit.csv", "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(cols)
            writer.writerows(rows)

        total = len(rows)
        missing_gender = sum(1 for r in rows if not r[cols.index("gender")])
        missing_ethnicity = sum(1 for r in rows if not r[cols.index("ethnicity")])
        missing_age = sum(1 for r in rows if not r[cols.index("age_range")])
        missing_prompt = sum(1 for r in rows if r[cols.index("has_prompt")] == "MISSING")
        missing_avatar = sum(1 for r in rows if r[cols.index("has_avatar")] == "MISSING")
        missing_email = sum(1 for r in rows if not r[cols.index("email")])
        missing_title = sum(1 for r in rows if not r[cols.index("title")])
        missing_firstname = sum(1 for r in rows if not r[cols.index("first_name")])

        print(f"=== AGENT PROFILE AUDIT ===")
        print(f"Total agents: {total}")
        print(f"Missing gender:      {missing_gender}/{total}")
        print(f"Missing ethnicity:   {missing_ethnicity}/{total}")
        print(f"Missing age_range:   {missing_age}/{total}")
        print(f"Missing title:       {missing_title}/{total}")
        print(f"Missing first_name:  {missing_firstname}/{total}")
        print(f"Missing system_prompt: {missing_prompt}/{total}")
        print(f"Missing avatar:      {missing_avatar}/{total}")
        print(f"Missing email:       {missing_email}/{total}")
        print(f"\nFull audit exported to /tmp/agent_audit.csv")

        print(f"\n=== AGENTS WITH GAPS (by department) ===")
        current_dept = None
        for r in rows:
            dept = r[cols.index("department")]
            gaps = []
            if not r[cols.index("gender")]:
                gaps.append("gender")
            if not r[cols.index("ethnicity")]:
                gaps.append("ethnicity")
            if not r[cols.index("age_range")]:
                gaps.append("age_range")
            if r[cols.index("has_prompt")] == "MISSING":
                gaps.append("prompt")
            if r[cols.index("has_avatar")] == "MISSING":
                gaps.append("avatar")
            if not r[cols.index("email")]:
                gaps.append("email")
            if gaps:
                if dept != current_dept:
                    print(f"\n--- {dept} ---")
                    current_dept = dept
                print(f"  {r[cols.index('display_name')]}: {', '.join(gaps)}")

    finally:
        conn.close()


if __name__ == "__main__":
    audit_agents()

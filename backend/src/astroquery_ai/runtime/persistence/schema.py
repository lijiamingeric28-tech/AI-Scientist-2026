"Existing SQLite schema and migrations; version and SQL unchanged."

from __future__ import annotations

import sqlite3

from astroquery_ai.runtime.codec import new_id

from astroquery_ai.runtime.errors import DomainError

SCHEMA_VERSION = 9

SCHEMA = "\nCREATE TABLE tasks (\n task_id TEXT PRIMARY KEY, revision INTEGER NOT NULL CHECK(revision>0),\n generation INTEGER NOT NULL, lifecycle TEXT NOT NULL, phase TEXT NOT NULL,\n science_state TEXT NOT NULL, kind TEXT NOT NULL, query_ref TEXT,\n delivery_ref TEXT, insight_ref TEXT, resume_required INTEGER NOT NULL DEFAULT 0,\n terminal_reason TEXT, title TEXT NOT NULL, created_at TEXT NOT NULL,\n updated_at TEXT NOT NULL, last_event_seq INTEGER NOT NULL DEFAULT 0\n);\nCREATE TABLE operations (\n task_id TEXT NOT NULL REFERENCES tasks(task_id), operation_id TEXT NOT NULL,\n request_hash TEXT NOT NULL, response_json TEXT NOT NULL,\n PRIMARY KEY(task_id,operation_id)\n);\nCREATE TABLE objects (\n task_id TEXT NOT NULL REFERENCES tasks(task_id), kind TEXT NOT NULL,\n object_id TEXT NOT NULL, version INTEGER NOT NULL, content_sha256 TEXT NOT NULL,\n payload BLOB NOT NULL, created_at TEXT NOT NULL,\n PRIMARY KEY(task_id,kind,object_id,version)\n);\nCREATE TABLE events (\n task_id TEXT NOT NULL REFERENCES tasks(task_id), seq INTEGER NOT NULL,\n event_id TEXT NOT NULL UNIQUE, payload BLOB NOT NULL,\n PRIMARY KEY(task_id,seq)\n);\nCREATE TABLE outbox (\n event_id TEXT PRIMARY KEY REFERENCES events(event_id), task_id TEXT NOT NULL,\n seq INTEGER NOT NULL, delivered_at TEXT\n);\nCREATE TABLE jobs (\n job_id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(task_id),\n logical_key TEXT NOT NULL, owner TEXT NOT NULL, kind TEXT NOT NULL,\n payload BLOB NOT NULL, status TEXT NOT NULL, generation INTEGER NOT NULL,\n lease_token TEXT, lease_owner TEXT, lease_until REAL, attempt_count INTEGER NOT NULL DEFAULT 0,\n result_ref TEXT, reason TEXT, created_at TEXT NOT NULL,\n UNIQUE(task_id,logical_key)\n);\nCREATE TABLE job_dependencies (\n job_id TEXT NOT NULL REFERENCES jobs(job_id), dependency_id TEXT NOT NULL REFERENCES jobs(job_id),\n resolution TEXT NOT NULL DEFAULT 'required', resolution_ref TEXT,\n PRIMARY KEY(job_id,dependency_id), CHECK(job_id<>dependency_id)\n);\nCREATE TABLE producers (\n task_id TEXT NOT NULL REFERENCES tasks(task_id), producer_id TEXT NOT NULL,\n revision INTEGER NOT NULL, state TEXT NOT NULL, watermark INTEGER NOT NULL,\n close_reason TEXT, PRIMARY KEY(task_id,producer_id)\n);\nCREATE TABLE campaigns (\n campaign_id TEXT PRIMARY KEY, cap_micros INTEGER NOT NULL CHECK(cap_micros>=0),\n smoke_cap_micros INTEGER NOT NULL, smoke_passed INTEGER NOT NULL DEFAULT 0,\n funded_cap_micros INTEGER NOT NULL DEFAULT 20000000,\n created_at TEXT NOT NULL\n);\nCREATE TABLE attempts (\n attempt_id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL REFERENCES campaigns(campaign_id),\n task_id TEXT NOT NULL REFERENCES tasks(task_id), job_id TEXT REFERENCES jobs(job_id),\n root_id TEXT NOT NULL, owner TEXT NOT NULL, model TEXT NOT NULL,\n request_hash TEXT NOT NULL, price_version TEXT NOT NULL,\n status TEXT NOT NULL, reserved_micros INTEGER NOT NULL CHECK(reserved_micros>=0),\n actual_micros INTEGER, input_bound INTEGER NOT NULL, output_bound INTEGER NOT NULL,\n input_tokens INTEGER, output_tokens INTEGER, smoke INTEGER NOT NULL,\n created_at TEXT NOT NULL, dispatched_at TEXT, settled_at TEXT, receipt BLOB,\n generation INTEGER NOT NULL, work_scope TEXT, wall_bound_seconds REAL NOT NULL DEFAULT 480\n);\nCREATE INDEX attempts_campaign ON attempts(campaign_id,status);\nCREATE INDEX jobs_ready ON jobs(status,task_id,created_at);\nCREATE TABLE dispatch_turns (task_id TEXT NOT NULL REFERENCES tasks(task_id),owner TEXT NOT NULL,turn INTEGER NOT NULL,PRIMARY KEY(task_id,owner));\nCREATE TABLE reviews (\n review_id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(task_id),\n revision INTEGER NOT NULL, basis_hash TEXT NOT NULL, logical_key TEXT NOT NULL,\n status TEXT NOT NULL, payload BLOB NOT NULL, answer BLOB, application BLOB,\n UNIQUE(task_id,logical_key)\n);\nCREATE TABLE settings (key TEXT PRIMARY KEY, payload BLOB NOT NULL, revision INTEGER NOT NULL);\nCREATE TABLE registry_releases (\n release_id TEXT PRIMARY KEY, content_sha256 TEXT NOT NULL, path TEXT NOT NULL,\n kind TEXT NOT NULL, synthetic INTEGER NOT NULL, imported_at TEXT NOT NULL\n);\nCREATE TABLE revocations (\n revision INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT UNIQUE NOT NULL,\n release_id TEXT NOT NULL REFERENCES registry_releases(release_id),\n dependency_id TEXT, reason TEXT NOT NULL, evidence BLOB NOT NULL\n);\nCREATE TABLE artifacts (\n artifact_id TEXT PRIMARY KEY, sha256 TEXT NOT NULL, byte_size INTEGER NOT NULL,\n relative_path TEXT NOT NULL, media_type TEXT NOT NULL, created_at TEXT NOT NULL,\n availability TEXT NOT NULL DEFAULT 'ready'\n);\nCREATE TABLE artifact_refs (\n task_id TEXT NOT NULL REFERENCES tasks(task_id), artifact_id TEXT NOT NULL REFERENCES artifacts(artifact_id),\n owner_id TEXT NOT NULL, PRIMARY KEY(task_id,artifact_id,owner_id)\n);\nCREATE TABLE http_attempts (\n attempt_id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(task_id),\n owner TEXT NOT NULL, service TEXT NOT NULL, request_hash TEXT NOT NULL,\n status TEXT NOT NULL, byte_count INTEGER NOT NULL DEFAULT 0,\n started_at TEXT NOT NULL, completed_at TEXT, status_code INTEGER, error_code TEXT,\n byte_bound INTEGER NOT NULL DEFAULT 0, wall_bound_seconds REAL NOT NULL DEFAULT 90,\n elapsed_seconds REAL NOT NULL DEFAULT 0, resource_scope TEXT NOT NULL DEFAULT 'general'\n);\nCREATE TABLE task_tombstones (task_id TEXT PRIMARY KEY REFERENCES tasks(task_id),cleanup_id TEXT NOT NULL,created_at TEXT NOT NULL);\nCREATE TABLE cleanups (cleanup_id TEXT PRIMARY KEY,task_id TEXT NOT NULL REFERENCES tasks(task_id),operation_id TEXT NOT NULL,request_hash TEXT NOT NULL,status TEXT NOT NULL,payload BLOB NOT NULL,UNIQUE(task_id,operation_id));\nCREATE TABLE artifact_leases (lease_id TEXT PRIMARY KEY,artifact_id TEXT NOT NULL REFERENCES artifacts(artifact_id),owner TEXT NOT NULL,expires_at REAL NOT NULL);\nCREATE TABLE replay_sources (replay_id TEXT PRIMARY KEY REFERENCES tasks(task_id),source_task_id TEXT NOT NULL REFERENCES tasks(task_id),payload BLOB NOT NULL);\n"


WORKBENCH_SCHEMA = """
CREATE TABLE registry_workspaces (workspace_id TEXT PRIMARY KEY, revision INTEGER NOT NULL, payload BLOB NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE registry_bundles (bundle_id TEXT PRIMARY KEY, payload BLOB NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE registry_operations (operation_id TEXT PRIMARY KEY, request_hash TEXT NOT NULL, response BLOB NOT NULL);
"""
SCHEMA += WORKBENCH_SCHEMA


def _migrate(self):
    conn = self.connect()
    try:
        initial_version = conn.execute("PRAGMA user_version").fetchone()[0]
        if initial_version > SCHEMA_VERSION:
            raise DomainError("DATABASE_TOO_NEW", "运行数据库版本高于当前软件，拒绝写入")
        if 0 < initial_version < SCHEMA_VERSION:
            destination = self.path.with_name(
                self.path.name + f".before-v{initial_version}-" + new_id() + ".sqlite3"
            )
            backup = sqlite3.connect(destination)
            try:
                conn.backup(backup)
            finally:
                backup.close()
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=FULL")
        conn.execute("BEGIN IMMEDIATE")
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version > SCHEMA_VERSION:
            raise DomainError("DATABASE_TOO_NEW", "运行数据库版本高于当前软件，拒绝写入")
        if version == 0:
            for statement in SCHEMA.split(";"):
                if statement.strip():
                    conn.execute(statement)
            conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        elif version == 1:
            conn.execute(
                "CREATE TABLE http_attempts (attempt_id TEXT PRIMARY KEY,task_id TEXT NOT NULL REFERENCES tasks(task_id),owner TEXT NOT NULL,service TEXT NOT NULL,request_hash TEXT NOT NULL,status TEXT NOT NULL,byte_count INTEGER NOT NULL DEFAULT 0,started_at TEXT NOT NULL,completed_at TEXT,status_code INTEGER,error_code TEXT)"
            )
        if 0 < version < 3:
            conn.execute(
                "ALTER TABLE campaigns ADD COLUMN funded_cap_micros INTEGER NOT NULL DEFAULT 20000000"
            )
            conn.execute(
                "CREATE TABLE dispatch_turns (task_id TEXT NOT NULL REFERENCES tasks(task_id),owner TEXT NOT NULL,turn INTEGER NOT NULL,PRIMARY KEY(task_id,owner))"
            )
            conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        if 0 < version < 4:
            conn.execute(
                "CREATE TABLE task_tombstones (task_id TEXT PRIMARY KEY REFERENCES tasks(task_id),cleanup_id TEXT NOT NULL,created_at TEXT NOT NULL)"
            )
            conn.execute(
                "CREATE TABLE cleanups (cleanup_id TEXT PRIMARY KEY,task_id TEXT NOT NULL REFERENCES tasks(task_id),operation_id TEXT NOT NULL,request_hash TEXT NOT NULL,status TEXT NOT NULL,payload BLOB NOT NULL,UNIQUE(task_id,operation_id))"
            )
            conn.execute(
                "CREATE TABLE artifact_leases (lease_id TEXT PRIMARY KEY,artifact_id TEXT NOT NULL REFERENCES artifacts(artifact_id),owner TEXT NOT NULL,expires_at REAL NOT NULL)"
            )
            conn.execute(
                "CREATE TABLE replay_sources (replay_id TEXT PRIMARY KEY REFERENCES tasks(task_id),source_task_id TEXT NOT NULL REFERENCES tasks(task_id),payload BLOB NOT NULL)"
            )
            conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        if 0 < version < 5:
            conn.execute(
                "ALTER TABLE artifacts ADD COLUMN availability TEXT NOT NULL DEFAULT 'ready'"
            )
            conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        if 0 < version < 6:
            conn.execute("ALTER TABLE attempts ADD COLUMN work_scope TEXT")
            conn.execute(
                "ALTER TABLE attempts ADD COLUMN wall_bound_seconds REAL NOT NULL DEFAULT 480"
            )
            conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        if 0 < version < 7:
            conn.execute(
                "ALTER TABLE http_attempts ADD COLUMN byte_bound INTEGER NOT NULL DEFAULT 0"
            )
            conn.execute(
                "ALTER TABLE http_attempts ADD COLUMN wall_bound_seconds REAL NOT NULL DEFAULT 90"
            )
            conn.execute(
                "ALTER TABLE http_attempts ADD COLUMN elapsed_seconds REAL NOT NULL DEFAULT 0"
            )
            conn.execute(
                "ALTER TABLE http_attempts ADD COLUMN resource_scope TEXT NOT NULL DEFAULT 'general'"
            )
            conn.execute(
                "UPDATE http_attempts SET elapsed_seconds=max(0,(julianday(coalesce(completed_at,started_at))-julianday(started_at))*86400),byte_bound=CASE WHEN completed_at IS NULL THEN 33554432 ELSE byte_count END"
            )
            conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        if 0 < version < 8:
            conn.execute(
                "ALTER TABLE job_dependencies ADD COLUMN resolution TEXT NOT NULL DEFAULT 'required'"
            )
            conn.execute("ALTER TABLE job_dependencies ADD COLUMN resolution_ref TEXT")
            conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        if 0 < version < 9:
            for statement in WORKBENCH_SCHEMA.split(';'):
                if statement.strip():
                    conn.execute(statement)
            conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()

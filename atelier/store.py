import json
import shutil
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path


def uid():
    return uuid.uuid4().hex


def default_profile():
    """Selection model and look shipped with the application (may be absent)."""
    from .config import resource_directory
    path = resource_directory() / "default_profile.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def pack(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


class Store:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.root / "library.sqlite3", timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA secure_delete=ON")
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        if version > 6:
            self.db.close()
            raise RuntimeError("Cette bibliothèque nécessite une version plus récente d’Atelier Photo.")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS profiles(
          id TEXT PRIMARY KEY, name TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE IF NOT EXISTS refs(
          id TEXT PRIMARY KEY, profile TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
          digest TEXT NOT NULL, name TEXT NOT NULL, data TEXT NOT NULL,
          UNIQUE(profile,digest));
        CREATE TABLE IF NOT EXISTS batches(
          id TEXT PRIMARY KEY, profile TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
          name TEXT NOT NULL, snapshot TEXT NOT NULL, selectivity REAL NOT NULL,
          created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS photos(
          id TEXT PRIMARY KEY, batch TEXT NOT NULL REFERENCES batches(id) ON DELETE CASCADE,
          path TEXT NOT NULL, data TEXT NOT NULL, UNIQUE(batch,path));
        CREATE TABLE IF NOT EXISTS feedback(
          profile TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
          photo TEXT NOT NULL,
          data TEXT NOT NULL, PRIMARY KEY(profile,photo));
        CREATE TABLE IF NOT EXISTS jobs(
          id TEXT PRIMARY KEY, profile TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
          kind TEXT NOT NULL, payload TEXT NOT NULL, cursor INTEGER NOT NULL DEFAULT 0,
          state TEXT NOT NULL DEFAULT 'pending', error TEXT NOT NULL DEFAULT '',
          created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS training(
          id TEXT PRIMARY KEY, profile TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
          reportage TEXT NOT NULL, role TEXT NOT NULL, path TEXT NOT NULL, data TEXT NOT NULL,
          UNIQUE(profile,reportage,role,path));
        CREATE TABLE IF NOT EXISTS reportages(
          id TEXT PRIMARY KEY, profile TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
          name TEXT NOT NULL, paths TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 0,
          ready INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS reference_groups(
          id TEXT PRIMARY KEY, profile TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
          name TEXT NOT NULL, paths TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 0,
          ready INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS reference_members(
          group_id TEXT NOT NULL REFERENCES reference_groups(id) ON DELETE CASCADE,
          ref_id TEXT NOT NULL REFERENCES refs(id) ON DELETE CASCADE, path TEXT NOT NULL,
          PRIMARY KEY(group_id,path));
        """)
        # v1 linked learned preferences to transient batch photos. Detach them
        # transactionally so deleting a batch cannot erase profile learning.
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            if any(row[2] == "photos" for row in self.db.execute("PRAGMA foreign_key_list(feedback)")):
                self.db.execute("ALTER TABLE feedback RENAME TO feedback_v1")
                self.db.execute("CREATE TABLE feedback(profile TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE, photo TEXT NOT NULL, data TEXT NOT NULL, PRIMARY KEY(profile,photo))")
                self.db.execute("INSERT INTO feedback SELECT profile,photo,data FROM feedback_v1")
                self.db.execute("DROP TABLE feedback_v1")
            columns = {r[1] for r in self.db.execute("PRAGMA table_info(jobs)")}
            if "batch" not in columns:
                self.db.execute("ALTER TABLE jobs ADD COLUMN batch TEXT REFERENCES batches(id) ON DELETE CASCADE")
                for row in self.rows("SELECT id,kind,payload FROM jobs WHERE kind IN ('analysis','export')"):
                    payload = json.loads(row["payload"])
                    batch = payload.get("batch")
                    if not batch and payload.get("items"):
                        batch = payload["items"][0].get("batch")
                    if batch and self.db.execute("SELECT 1 FROM batches WHERE id=?", (batch,)).fetchone():
                        self.db.execute("UPDATE jobs SET batch=? WHERE id=?", (batch, row["id"]))
            # v3: the applied filter can be switched off for a whole batch.
            if "filter_enabled" not in {r[1] for r in self.db.execute("PRAGMA table_info(batches)")}:
                self.db.execute("ALTER TABLE batches ADD COLUMN filter_enabled INTEGER NOT NULL DEFAULT 1")
            # v4: selection model and colour look learned from sorted reportages.
            if "model" not in {r[1] for r in self.db.execute("PRAGMA table_info(profiles)")}:
                self.db.execute("ALTER TABLE profiles ADD COLUMN model TEXT")
            self.db.execute("CREATE INDEX IF NOT EXISTS training_profile ON training(profile,reportage)")
            self.db.execute("CREATE INDEX IF NOT EXISTS reportages_profile ON reportages(profile)")
            self.db.execute("CREATE INDEX IF NOT EXISTS batches_profile ON batches(profile)")
            self.db.execute("CREATE INDEX IF NOT EXISTS jobs_batch_state ON jobs(batch,state)")
            self.db.execute("CREATE INDEX IF NOT EXISTS jobs_profile_state ON jobs(profile,state)")
            if version < 5:
                for job in self.rows("SELECT profile,payload,state FROM jobs WHERE kind='training' ORDER BY rowid"):
                    payload = json.loads(job["payload"])
                    self._register_reportages(job["profile"], payload, completed=job["state"] == "done")
            if version < 6:
                for row in self.rows("SELECT * FROM refs ORDER BY rowid"):
                    group = self._legacy_reference_group(row["profile"])
                    self.db.execute("INSERT OR IGNORE INTO reference_members VALUES(?,?,?)",
                                    (group, row["id"], row["id"]))
            self.db.execute("PRAGMA user_version=6")

    def close(self):
        self.db.close()

    def recover_interrupted_jobs(self):
        """Call only after the UI has acquired its exclusive application lock."""
        with self.db:
            self.db.execute("UPDATE jobs SET state='paused', error='Traitement interrompu ; reprise disponible.' WHERE state='running'")

    @contextmanager
    def atomic(self):
        with self.db:
            yield

    def rows(self, sql, args=()):
        return [dict(row) for row in self.db.execute(sql, args)]

    def profiles(self):
        return self.rows("SELECT id, name FROM profiles ORDER BY name")

    def create_profile(self, name):
        name = name.strip()
        if not name:
            raise ValueError("Le profil doit avoir un nom.")
        identifier = uid()
        with self.db:
            self.db.execute("INSERT INTO profiles(id,name) VALUES(?,?)", (identifier, name))
        return identifier

    def rename_profile(self, identifier, name):
        if not name.strip():
            raise ValueError("Le profil doit avoir un nom.")
        with self.db:
            self.db.execute("UPDATE profiles SET name=? WHERE id=?", (name.strip(), identifier))

    def private_dir(self, profile, *parts):
        # Identifiers are generated by this application, never source filenames.
        target = (self.root / "profiles" / profile).joinpath(*parts).resolve()
        if not target.is_relative_to(self.root / "profiles") or target == self.root / "profiles":
            raise ValueError("Chemin interne invalide")
        target.mkdir(parents=True, exist_ok=True)
        return target

    def wipe(self, profile, delete=False):
        target = (self.root / "profiles" / profile).resolve()
        if not target.is_relative_to(self.root / "profiles") or target == self.root / "profiles":
            raise ValueError("Chemin interne invalide")
        with self.db:
            for table in ("feedback", "jobs", "batches", "reference_groups", "refs", "training", "reportages"):
                self.db.execute(f"DELETE FROM {table} WHERE profile=?", (profile,))
            if delete:
                self.db.execute("DELETE FROM profiles WHERE id=?", (profile,))
            else:
                self.db.execute("UPDATE profiles SET version=version+1, model=NULL WHERE id=?", (profile,))
        if target.exists():
            shutil.rmtree(target)
        self.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        self.db.execute("VACUUM")

    def references(self, profile, *, active_only=False):
        active = (" AND EXISTS (SELECT 1 FROM reference_members m JOIN reference_groups g ON g.id=m.group_id "
                  "WHERE m.ref_id=refs.id AND g.profile=refs.profile AND g.enabled=1 AND g.ready=1)") if active_only else ""
        return [dict(row, data=json.loads(row["data"]))
                for row in self.rows("SELECT * FROM refs WHERE profile=?" + active + " ORDER BY rowid", (profile,))]

    def _legacy_reference_group(self, profile):
        group = "legacy-" + profile
        self.db.execute("INSERT OR IGNORE INTO reference_groups VALUES(?,?,?,?,1,1)",
                        (group, profile, "Références déjà ajoutées", "[]"))
        return group

    def reference_groups(self, profile):
        groups = self.rows("SELECT * FROM reference_groups WHERE profile=? ORDER BY rowid", (profile,))
        for group in groups:
            members = self.rows("SELECT ref_id,path FROM reference_members WHERE group_id=?", (group["id"],))
            group["paths"] = json.loads(group["paths"]) or [m["path"] for m in members]
            group["count"] = len({m["ref_id"] for m in members})
        return groups

    def has_reference(self, group, path):
        return self.db.execute("SELECT 1 FROM reference_members WHERE group_id=? AND path=?",
                               (group, str(path))).fetchone() is not None

    def link_reference(self, profile, group, identifier, path):
        with self.db:
            if not self.db.execute("SELECT 1 FROM reference_groups WHERE id=? AND profile=?", (group, profile)).fetchone():
                raise ValueError("Groupe de références introuvable dans ce profil.")
            if not self.db.execute("SELECT 1 FROM refs WHERE id=? AND profile=?", (identifier, profile)).fetchone():
                raise ValueError("Référence introuvable dans ce profil.")
            self.db.execute("INSERT OR IGNORE INTO reference_members VALUES(?,?,?)", (group, identifier, str(path)))

    def add_reference(self, profile, identifier, digest, name, data, *, group=None, path=None):
        legacy = group is None
        with self.db:
            cursor = self.db.execute("INSERT OR IGNORE INTO refs VALUES(?,?,?,?,?)", (identifier, profile, digest, name, pack(data)))
            reference = self.db.execute("SELECT id FROM refs WHERE profile=? AND digest=?", (profile, digest)).fetchone()[0]
            if group is None:
                group = self._legacy_reference_group(profile)
                path = reference
            elif not self.db.execute("SELECT 1 FROM reference_groups WHERE id=? AND profile=?", (group, profile)).fetchone():
                raise ValueError("Groupe de références introuvable dans ce profil.")
            self.db.execute("INSERT OR IGNORE INTO reference_members VALUES(?,?,?)", (group, reference, str(path)))
            if cursor.rowcount and legacy:
                self.db.execute("UPDATE profiles SET version=version+1 WHERE id=?", (profile,))
        return bool(cursor.rowcount)

    def snapshot(self, profile, model):
        """Frozen copy of everything a batch needs: references, corrections, learned model."""
        record = self.db.execute("SELECT * FROM profiles WHERE id=?", (profile,)).fetchone()
        if record is None:
            raise ValueError("Profil introuvable")
        learned = self.model(profile) or {}
        default = default_profile()
        selector = next((s for s in (learned.get("selector"), default.get("selector"))
                         if s and s.get("encoder") == model), None)
        feedback = [json.loads(r["data"]) for r in self.rows("SELECT data FROM feedback WHERE profile=?", (profile,))]
        return {"version": record["version"], "model": model,
                "references": [r["data"] for r in self.references(profile, active_only=True)],
                "feedback": [f for f in feedback if f.get("model") == model],
                "selector": selector,
                "look": learned.get("look") or default.get("look")}

    def model(self, profile):
        row = self.db.execute("SELECT model FROM profiles WHERE id=?", (profile,)).fetchone()
        return json.loads(row["model"]) if row and row["model"] else None

    def set_model(self, profile, model):
        with self.db:
            self.db.execute("UPDATE profiles SET model=?, version=version+1 WHERE id=?", (pack(model) if model else None, profile))

    def add_training(self, identifier, profile, reportage, role, path, data):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO training VALUES(?,?,?,?,?,?)", (identifier, profile, reportage, role, str(path), pack(data)))

    def has_training(self, profile, reportage, role, path):
        return self.db.execute("SELECT 1 FROM training WHERE profile=? AND reportage=? AND role=? AND path=?",
                               (profile, reportage, role, str(path))).fetchone() is not None

    def _register_reportages(self, profile, payload, completed=False):
        records = payload.get("catalog", payload.get("reportages", []))
        if payload.get("reportage"):
            records = [{"id": payload["reportage"], "name": payload.get("name", "Reportage")}]
        errors = {e.get("reportage", payload.get("reportage")) for e in payload.get("errors", [])}
        by_reportage = {}
        for item in payload.get("items", []):
            if item["role"] == "reference":
                continue
            identifier = item.get("reportage", payload.get("reportage"))
            by_reportage.setdefault(identifier, {"rush": [], "kept": []})[item["role"]].append(item["path"])
        for record in records:
            paths = {role: record.get(role, by_reportage.get(record["id"], {}).get(role, []))
                     for role in ("rush", "kept")}
            ready = completed and record["id"] not in errors
            self.db.execute("INSERT OR IGNORE INTO reportages(id,profile,name,paths,enabled,ready) VALUES(?,?,?,?,?,?)",
                            (record["id"], profile, record["name"], pack(paths), int(ready), int(ready)))

    def forget_source(self, profile, owner, role, path):
        """Drop a source photo set aside as corrupt from a reportage or reference group."""
        path = str(path)
        with self.db:
            row = self.db.execute("SELECT paths FROM reportages WHERE profile=? AND id=?", (profile, owner)).fetchone()
            if row and role in ("rush", "kept"):
                paths = json.loads(row["paths"])
                paths[role] = [p for p in paths.get(role, []) if p != path]
                self.db.execute("UPDATE reportages SET paths=? WHERE profile=? AND id=?", (pack(paths), profile, owner))
            row = self.db.execute("SELECT paths FROM reference_groups WHERE profile=? AND id=?", (profile, owner)).fetchone()
            if row and role == "reference":
                paths = [p for p in json.loads(row["paths"]) if p != path]
                self.db.execute("UPDATE reference_groups SET paths=? WHERE profile=? AND id=?", (pack(paths), profile, owner))

    def reportages(self, profile):
        records = self.rows("SELECT * FROM reportages WHERE profile=? ORDER BY rowid", (profile,))
        for record in records:
            record.update(json.loads(record.pop("paths")))
        return records

    def training(self, profile, *, completed_only=False, include_job=None):
        allowed = None
        if completed_only:
            allowed = {r["id"] for r in self.reportages(profile) if r["enabled"] and r["ready"]}
            if include_job:
                payload = self.job(include_job)["payload"]
                ids = {r["id"] for r in payload.get("reportages", [])}
                if payload.get("reportage"):  # Legacy single-reportage tasks remain resumable.
                    ids.add(payload["reportage"])
                failed = {e.get("reportage", payload.get("reportage")) for e in payload.get("errors", [])}
                allowed.update(ids - failed)
        return [dict(r, data=json.loads(r["data"]))
                for r in self.rows("SELECT * FROM training WHERE profile=? ORDER BY rowid", (profile,))
                if allowed is None or r["reportage"] in allowed]

    def complete_training(self, identifier, model, payload):
        """Publish the model and mark its source task done in one transaction."""
        job = self.job(identifier)
        base = (self.root / "profiles" / job["profile"] / "training").resolve()
        removed_paths = [(base / removed).resolve() for removed in payload.get("removed_reportages", [])]
        orphan_paths = []
        if not base.is_relative_to(self.root / "profiles") or any(target.parent != base for target in removed_paths):
            raise ValueError("Chemin interne invalide")
        with self.db:
            self.db.execute("UPDATE profiles SET model=?, version=version+1 WHERE id=?", (pack(model) if model else None, job["profile"]))
            if "selected_reportages" in payload:
                self.db.execute("UPDATE reportages SET enabled=0 WHERE profile=?", (job["profile"],))
                active = payload["selected_reportages"]
                for removed in payload.get("removed_reportages", []):
                    self.db.execute("DELETE FROM training WHERE profile=? AND reportage=?", (job["profile"], removed))
                    self.db.execute("DELETE FROM reportages WHERE profile=? AND id=?", (job["profile"], removed))
                self.db.execute("UPDATE jobs SET state='superseded' WHERE profile=? AND kind='training' AND id!=? AND state!='done'",
                                (job["profile"], identifier))
            else:
                active = [r["id"] for r in payload.get("reportages", [])]
                if payload.get("reportage"):
                    active.append(payload["reportage"])
                failed = {e.get("reportage", payload.get("reportage")) for e in payload.get("errors", [])}
                active = [r for r in active if r not in failed]
            self.db.executemany("UPDATE reportages SET enabled=1,ready=1 WHERE profile=? AND id=?",
                                [(job["profile"], r) for r in active])
            if "reference_catalog" in payload:
                self.db.execute("UPDATE jobs SET state='superseded' WHERE profile=? AND kind='references' AND state!='done'",
                                (job["profile"],))
                self.db.execute("UPDATE reference_groups SET enabled=0 WHERE profile=?", (job["profile"],))
                self.db.executemany("DELETE FROM reference_groups WHERE profile=? AND id=?",
                                    [(job["profile"], r) for r in payload["removed_reference_groups"]])
                self.db.executemany("UPDATE reference_groups SET enabled=1,ready=1 WHERE profile=? AND id=?",
                                    [(job["profile"], r) for r in payload["selected_reference_groups"]])
                # A photo shared by two groups stays available while either group exists.
                orphan_ids = self.rows("SELECT id FROM refs WHERE profile=? AND NOT EXISTS "
                                       "(SELECT 1 FROM reference_members WHERE ref_id=refs.id)", (job["profile"],))
                reference_base = (base.parent / "references").resolve()
                orphan_paths = [(reference_base / f"{r['id']}.png").resolve() for r in orphan_ids]
                if any(path.parent != reference_base for path in orphan_paths):
                    raise ValueError("Chemin interne invalide")
                self.db.execute("DELETE FROM refs WHERE profile=? AND NOT EXISTS "
                                "(SELECT 1 FROM reference_members WHERE ref_id=refs.id)", (job["profile"],))
            self.db.execute("UPDATE jobs SET state='done', error='', payload=? WHERE id=?", (pack(payload), identifier))

        # Only application-owned samples are removed; source photographs stay intact.
        for target in removed_paths + orphan_paths:
            try:
                if target in orphan_paths:
                    target.unlink(missing_ok=True)
                elif target.exists():
                    shutil.rmtree(target)
            except OSError:
                payload.setdefault("warnings", []).append("Un cache d’exemples retirés n’a pas pu être effacé ; il ne participe plus à l’apprentissage.")
                self.update_job(identifier, payload=payload)

    def create_batch(self, profile, name, snapshot, selectivity):
        identifier = uid()
        with self.db:
            self.db.execute("INSERT INTO batches(id,profile,name,snapshot,selectivity) VALUES(?,?,?,?,?)", (identifier, profile, name, pack(snapshot), selectivity))
        return identifier

    def batches(self, profile):
        return self.rows("SELECT id,name,created FROM batches WHERE profile=? ORDER BY rowid DESC", (profile,))

    def set_filter(self, batch_id, enabled):
        with self.db:
            self.db.execute("UPDATE batches SET filter_enabled=? WHERE id=?", (int(bool(enabled)), batch_id))

    def learning_count(self, profile):
        return self.db.execute("SELECT COUNT(*) FROM feedback WHERE profile=?", (profile,)).fetchone()[0]

    def clear_feedback(self, profile):
        """Forget only validated batch corrections; keep training and existing batches."""
        with self.db:
            if not self.db.execute("SELECT 1 FROM profiles WHERE id=?", (profile,)).fetchone():
                raise ValueError("Profil introuvable.")
            count = self.db.execute("DELETE FROM feedback WHERE profile=?", (profile,)).rowcount
            if count:
                self.db.execute("UPDATE profiles SET version=version+1 WHERE id=?", (profile,))
        return count

    def delete_batch(self, batch_id, profile):
        batch = self.batch(batch_id)
        if batch["profile"] != profile:
            raise ValueError("Ce lot n’appartient pas au profil sélectionné.")
        if self.db.execute("SELECT 1 FROM jobs WHERE batch=? AND state='running'", (batch_id,)).fetchone():
            raise ValueError("Suspendez le traitement de ce lot avant de le supprimer.")
        base = (self.root / "profiles" / profile / "batches").resolve()
        target = (base / batch_id).resolve()
        if not base.is_relative_to(self.root / "profiles") or not target.is_relative_to(base) or target == base:
            raise ValueError("Chemin interne invalide")
        # Rename first: a locked cache must not leave a deleted database record.
        tombstone = base / (".deleted-" + uid())
        if target.exists():
            target.rename(tombstone)
        try:
            with self.db:
                self.db.execute("DELETE FROM batches WHERE id=? AND profile=?", (batch_id, profile))
        except BaseException:
            if tombstone.exists():
                tombstone.rename(target)
            raise
        if tombstone.exists():
            shutil.rmtree(tombstone)
        # SQLite reuses freed pages; avoid a full VACUUM on every UI deletion.
        self.db.execute("PRAGMA wal_checkpoint(PASSIVE)")

    def batch(self, identifier):
        record = self.db.execute("SELECT * FROM batches WHERE id=?", (identifier,)).fetchone()
        if record is None:
            raise ValueError("Lot introuvable")
        row = dict(record)
        row["snapshot"] = json.loads(row["snapshot"])
        row["filter_enabled"] = bool(row["filter_enabled"])
        return row

    def photos(self, batch):
        return [dict(r, data=json.loads(r["data"])) for r in self.rows("SELECT * FROM photos WHERE batch=? ORDER BY rowid", (batch,))]

    def save_photo(self, identifier, batch, path, data):
        with self.db:
            self.db.execute("INSERT INTO photos VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data", (identifier, batch, str(path), pack(data)))

    def save_photos(self, rows):
        with self.db:
            self.db.executemany("UPDATE photos SET data=? WHERE id=? AND batch=?", [(pack(r["data"]), r["id"], r["batch"]) for r in rows])

    def new_job(self, profile, kind, payload):
        identifier = uid()
        with self.db:
            if kind == "training":
                self._register_reportages(profile, payload)
                for group in payload.get("reference_catalog", []):
                    self.db.execute("INSERT OR IGNORE INTO reference_groups(id,profile,name,paths) VALUES(?,?,?,?)",
                                    (group["id"], profile, group["name"], pack(group["paths"])))
            self.db.execute("INSERT INTO jobs(id,profile,kind,payload,batch) VALUES(?,?,?,?,?)", (identifier, profile, kind, pack(payload), payload.get("batch")))
        return identifier

    def job(self, identifier):
        row = dict(self.db.execute("SELECT * FROM jobs WHERE id=?", (identifier,)).fetchone())
        row["payload"] = json.loads(row["payload"])
        return row

    def update_job(self, identifier, **fields):
        allowed = {"cursor", "state", "error", "payload", "batch"}
        if "payload" in fields and fields["payload"].get("batch"):
            fields["batch"] = fields["payload"]["batch"]
        if not fields.keys() <= allowed:
            raise ValueError("Champ de tâche inconnu")
        values = [pack(v) if k == "payload" else v for k, v in fields.items()]
        with self.db:
            self.db.execute("UPDATE jobs SET " + ",".join(f"{k}=?" for k in fields) + " WHERE id=?", (*values, identifier))

    def unfinished_jobs(self, profile):
        return self.rows("SELECT * FROM jobs WHERE profile=? AND state NOT IN ('done','superseded') ORDER BY rowid", (profile,))

    def delete_job(self, identifier, profile):
        row = self.db.execute("SELECT * FROM jobs WHERE id=? AND profile=?", (identifier, profile)).fetchone()
        if row is None:
            raise ValueError("Tâche introuvable dans ce profil.")
        if row["state"] not in ("pending", "paused", "failed"):
            raise ValueError("Seule une tâche en attente, suspendue ou interrompue peut être supprimée.")
        if row["kind"] == "analysis" and row["batch"]:
            # Deleting only the job would make batch_ready accept partial results.
            self.delete_batch(row["batch"], profile)
        else:
            with self.db:
                self.db.execute("DELETE FROM jobs WHERE id=? AND profile=?", (identifier, profile))
        # Training samples/catalog and learned corrections belong to the profile;
        # exported files belong to the user, not to the resumable task.

    def validate(self, batch_id, profile=None):
        """Upsert explicit corrections. Revalidation is idempotent and reversible."""
        batch = self.batch(batch_id)
        if profile is not None and batch["profile"] != profile:
            raise ValueError("Ce lot n’appartient pas au profil sélectionné.")
        if not self.batch_ready(batch_id):
            raise ValueError("L’analyse ou le tri de ce lot doit être terminé avant validation.")
        from .imaging import NEUTRAL
        changed = 0
        explicit_count = 0
        with self.db:
            for row in self.photos(batch_id):
                d = row["data"]
                if "error" in d:
                    continue
                decision = d["decision"] if d.get("manual_decision") or d["decision"] != d["proposed"] else None
                adjusted = [k for k, v in d["initial_recipe"].items() if abs(d["recipe"][k] - v) > 1e-6]
                base = d.get("base_recipe", NEUTRAL)
                delta = {k: d["recipe"][k] - base[k] for k in adjusted}
                explicit = decision is not None or bool(adjusted)
                explicit_count += bool(explicit)
                old = self.db.execute("SELECT data FROM feedback WHERE profile=? AND photo=?", (batch["profile"], row["id"])).fetchone()
                value = pack({"embedding": d["embedding"], "model": batch["snapshot"]["model"],
                              "decision": decision, "delta": delta}) if explicit else None
                if (old[0] if old else None) != value:
                    changed += 1
                    if value is None:
                        self.db.execute("DELETE FROM feedback WHERE profile=? AND photo=?", (batch["profile"], row["id"]))
                    else:
                        self.db.execute("INSERT INTO feedback VALUES(?,?,?) ON CONFLICT(profile,photo) DO UPDATE SET data=excluded.data", (batch["profile"], row["id"], value))
                d["validated"] = True
                self.db.execute("UPDATE photos SET data=? WHERE id=?", (pack(d), row["id"]))
            if changed:
                self.db.execute("UPDATE profiles SET version=version+1 WHERE id=?", (batch["profile"],))
        return {"corrections": explicit_count, "updated": changed, "total": self.learning_count(batch["profile"])}

    def batch_ready(self, batch_id):
        return self.db.execute("SELECT 1 FROM jobs WHERE batch=? AND kind IN ('analysis','selection') "
                               "AND state NOT IN ('done','superseded') LIMIT 1", (batch_id,)).fetchone() is None


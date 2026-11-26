import os
import shutil
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image

from . import performance
from .analysis import propose, reselect
from .config import QUARANTINE_DIR
from .dino import DinoEncoder
from .imaging import CorruptPhoto, capture_time, decode, digest, features
from .progress import ProgressEstimator
from .recovery import recover_image
from .store import Store, pack, uid
from .training import learn
from .xmp import companions


def quarantine(path):
    """Move a corrupt photo and its XMP sidecar into ``Photos corrompues`` beside it.

    Returns the new path, or None when the folder is read-only (the photo is then
    only excluded). A disk that cannot be read stays a resumable OSError.
    """
    source = Path(path)
    with open(source, "rb") as stream:
        while stream.read(1024 * 1024):
            pass
    try:
        folder = source.parent / QUARANTINE_DIR
        folder.mkdir(exist_ok=True)
        for number in range(1, 10000):
            target = folder / (source.name if number == 1 else f"{source.stem} ({number}){source.suffix}")
            if not target.exists():
                break
        else:
            return None
        sidecars = companions(source)
        # Same volume; never overwrite an earlier quarantined file.
        os.rename(source, target)
    except PermissionError:
        return None
    for companion in sidecars:
        # photo.xmp or photo.nef.xmp follows the renamed photo.
        moved = target.with_name(target.stem + companion.name[len(source.stem):])
        try:
            if not moved.exists():
                os.rename(companion, moved)
        except OSError:
            pass
    return str(target)


def analysis_job(store, profile, paths, selectivity=.5):
    return store.new_job(profile, "analysis", {"paths": paths, "selectivity": selectivity, "batch": None})


def _check_selection(store, batch, selectivity, identifier=""):
    if not 0 <= selectivity <= 1:
        raise ValueError("Sélectivité invalide.")
    pending = store.rows("SELECT kind FROM jobs WHERE batch=? AND id!=? "
                         "AND kind IN ('analysis','selection','export') AND state NOT IN ('done','superseded')",
                         (batch, identifier))
    if any(job["kind"] == "export" for job in pending):
        raise ValueError("Terminez l’export en cours ou supprimez sa tâche dans « Gérer les tâches » avant de modifier le tri.")
    if pending:
        raise ValueError("Terminez l’analyse ou le tri de ce lot via « Gérer les tâches » avant de modifier sa sélectivité.")


def selection_job(store, batch, selectivity):
    record = store.batch(batch)
    _check_selection(store, batch, selectivity)
    return store.new_job(record["profile"], "selection", {"batch": batch, "selectivity": selectivity})


def _run_selection(store, identifier, payload, events, cancel):
    batch = payload["batch"]
    _check_selection(store, batch, payload["selectivity"], identifier)
    events.put({"type": "phase", "label": "Mise à jour du tri du lot…"})
    rows = reselect(store.photos(batch), store.batch(batch)["snapshot"], payload["selectivity"], cancel)
    if rows is None or cancel.is_set():
        store.update_job(identifier, state="paused")
        events.put({"type": "paused", "job": identifier})
        return
    # Publish the new setting, decisions and task state together, or not at all.
    with store.atomic():
        store.db.executemany("UPDATE photos SET data=? WHERE id=? AND batch=?",
                             [(pack(row["data"]), row["id"], batch) for row in rows])
        store.db.execute("UPDATE batches SET selectivity=? WHERE id=?", (payload["selectivity"], batch))
        store.db.execute("UPDATE jobs SET state='done' WHERE id=?", (identifier,))
    events.put({"type": "done", "job": identifier, "total": len(rows)})


def training_job(store, profile, rush, kept, name="Reportage"):
    """Teach the profile with a sorted reportage: complete rush + delivered photos."""
    return training_jobs(store, profile, [{"rush": rush, "kept": kept, "name": name}])


def training_jobs(store, profile, reportages):
    """One resumable task, separate matching per reportage, one final model fit."""
    items, records, seen = [], [], set()
    for reportage in reportages:
        rush = list(dict.fromkeys(str(Path(p).resolve()) for p in reportage["rush"]))
        kept = list(dict.fromkeys(str(Path(p).resolve()) for p in reportage["kept"]))
        if not rush or not kept:
            raise ValueError("Chaque reportage doit contenir un rush et des photos choisies.")
        # Selected originals can also be in the rush. Keep both roles: removing
        # them from the rush would turn their neighbours into false positives.
        overlap = seen.intersection(rush)
        if overlap:
            raise ValueError("Les rushs ajoutés contiennent des fichiers communs. Ajoutez chaque reportage une seule fois.")
        seen.update(rush)
        identifier = uid()
        records.append({"id": identifier, "name": reportage.get("name", "Reportage")})
        items.extend({"reportage": identifier, "role": role, "path": p}
                     for role, paths in (("rush", rush), ("kept", kept)) for p in paths)
    if not records:
        raise ValueError("Ajoutez au moins un reportage trié.")
    return store.new_job(profile, "training", {"reportages": records, "items": items, "errors": [], "warnings": []})


def training_update_job(store, profile, reportages, reference_groups=None):
    """Rebuild from the checked catalog, reusing stored samples for existing photos."""
    existing = {r["id"]: r for r in store.reportages(profile)}
    records, selected, items, seen, identifiers = [], [], [], set(), set()
    for record in reportages:
        identifier = record.get("id")
        if identifier:
            if identifier not in existing or identifier in identifiers:
                raise ValueError("Reportage introuvable dans ce profil ou présent plusieurs fois.")
            source = existing[identifier]
        else:
            identifier, source = uid(), record
        identifiers.add(identifier)
        paths = {role: list(dict.fromkeys(str(Path(p).resolve()) for p in source[role])) for role in ("rush", "kept")}
        if identifier not in existing and (not paths["rush"] or not paths["kept"]):
            raise ValueError("Chaque reportage doit contenir un rush et des photos retenues.")
        if seen.intersection(paths["rush"]):
            raise ValueError("Ce rush est déjà présent dans un autre reportage du profil.")
        seen.update(paths["rush"])
        records.append({"id": identifier, "name": source["name"], **paths})
        if record.get("enabled", True):
            selected.append(identifier)
            items.extend({"reportage": identifier, "role": role, "path": path}
                         for role in ("rush", "kept") for path in paths[role])
    payload = {
        "catalog": records, "reportages": [{"id": r["id"], "name": r["name"]} for r in records if r["id"] in selected],
        "selected_reportages": selected, "removed_reportages": sorted(existing.keys() - identifiers),
        "items": items, "errors": [], "warnings": [],
    }
    if reference_groups is not None:
        existing_groups = {g["id"]: g for g in store.reference_groups(profile)}
        groups, active, group_ids = [], [], set()
        for group in reference_groups:
            identifier = group.get("id")
            if identifier:
                if identifier not in existing_groups or identifier in group_ids:
                    raise ValueError("Groupe de références introuvable dans ce profil ou présent plusieurs fois.")
                source = existing_groups[identifier]
                paths = source["paths"]
            else:
                identifier, source = uid(), group
                paths = list(dict.fromkeys(str(Path(p).resolve()) for p in source["paths"]))
            if identifier not in existing_groups and not paths:
                raise ValueError("Chaque groupe de références doit contenir des photos.")
            group_ids.add(identifier)
            groups.append({"id": identifier, "name": source["name"], "paths": paths})
            if group.get("enabled", True):
                active.append(identifier)
                items.extend({"reportage": identifier, "role": "reference", "path": path}
                             for path in paths if not store.has_reference(identifier, path))
        payload.update(reference_catalog=groups, selected_reference_groups=active,
                       removed_reference_groups=sorted(existing_groups.keys() - group_ids))
    return store.new_job(profile, "training", payload)


def prepare_reference(path, encoder, checksum=None):
    """CPU/IO work for one reference; the database stays in the job thread.

    A reference only shows what the photographer likes: its content (DINOv3
    vector) and its technical measures. Sidecars are not read.
    """
    checksum = checksum or digest(path)
    image = decode(path)
    data = {"features": features(image), "embedding": encoder.encode(image), "model": encoder.version}
    return {"digest": checksum, "data": data, "image": image}


def _save_reference(store, profile, path, encoder, group, prepared=None):
    """``prepared`` returns the work of prepare_reference, possibly done ahead."""
    if store.has_reference(group, path):
        return
    reference = None
    if prepared:
        # Prepared ahead in parallel: its digest identifies exactly the analysed bytes.
        reference = prepared()
        checksum = reference["digest"]
    else:
        checksum = digest(path)
    existing = store.db.execute("SELECT id FROM refs WHERE profile=? AND digest=?", (profile, checksum)).fetchone()
    if existing:
        store.link_reference(profile, group, existing["id"], path)
        return
    if reference is None:
        reference = prepare_reference(path, encoder, checksum)
    ref_id = uid()
    proxy = store.private_dir(profile, "references") / f"{ref_id}.png"
    reference["image"].save(proxy, compress_level=1)
    if not store.add_reference(profile, ref_id, checksum, Path(path).name, reference["data"], group=group, path=path):
        proxy.unlink(missing_ok=True)


def _save_training_photo(store, profile, reportage, item, photo, encoder_version):
    data = {"name": Path(item["path"]).name, "stats": photo["features"], "embedding": photo["embedding"],
            "time": photo["time"], "model": encoder_version}
    store.add_training(uid(), profile, reportage, item["role"], item["path"], data)


def _finish_training(store, identifier, profile, payload, encoder_version):
    if "selected_reportages" in payload:
        selected = set(payload["selected_reportages"])
        if payload.get("errors"):
            raise ValueError("Certains fichiers sont illisibles : le profil précédent est conservé. Corrigez-les ou retirez les reportages concernés.")
        rows = [r for r in store.training(profile) if r["reportage"] in selected]
        if selected:
            try:
                model, warnings = learn(rows, encoder_version)
            except ValueError as exc:
                # A removal must never leave the removed examples in the model,
                # even when the remaining set is too small to train on its own.
                model = None
                warnings = [str(exc), "Sélection par défaut utilisée jusqu’à l’ajout de reportages exploitables."]
        else:
            model, warnings = None, []
        payload["warnings"] = warnings
        payload["summary"] = {k: (model or {}).get(k, 0) for k in ("reportages", "photos", "kept")}
        payload["summary"]["reference_groups"] = len(payload.get("selected_reference_groups", []))
        store.complete_training(identifier, model, payload)
        return

    rows = store.training(profile, completed_only=True, include_job=identifier)
    current = {r["id"] for r in payload["reportages"]}
    if not any(row["reportage"] in current for row in rows):
        raise ValueError("Aucun nouveau reportage complet exploitable. Vérifiez les fichiers indiqués en erreur.")
    model, warnings = learn(rows, encoder_version)
    if payload.get("errors"):
        warnings.append("Les reportages contenant des fichiers illisibles ont été exclus de l’apprentissage.")
    payload["warnings"] = warnings
    payload["summary"] = {k: model.get(k) for k in ("reportages", "photos", "kept")}
    store.complete_training(identifier, model, payload)


def export_job(store, batch, destination):
    """Copy the kept photos, byte for byte, with their XMP sidecars."""
    if not store.batch_ready(batch):
        raise ValueError("Terminez l’analyse ou le tri du lot avant l’export.")
    photos = store.photos(batch)
    items = [r for r in photos if "error" not in r["data"] and r["data"]["decision"] == "keep"]
    if not items:
        raise ValueError("Aucune photo retenue à exporter.")
    if any(not r["data"].get("validated") for r in photos if "error" not in r["data"]):
        raise ValueError("Validez les propositions avant de les exporter.")
    record = store.batch(batch)
    export_items = [{"id": r["id"], "path": r["path"], "data": {"digest": r["data"]["digest"]}} for r in items]
    return store.new_job(record["profile"], "export", {
        "batch": batch, "items": export_items, "destination": str(Path(destination).resolve()),
        "outputs": [], "errors": []})


def _reserve(path):
    try:
        os.close(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
        return True
    except FileExistsError:
        return False


def _publish(destination, target, write):
    """Write through a same-volume temporary file, then replace our reservation."""
    fd, temporary = tempfile.mkstemp(prefix=".atelier-", suffix=".tmp", dir=destination)
    try:
        with open(fd, "wb") as stream:
            write(stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def recover_one(path, destination):
    source, destination = Path(path), Path(destination)
    data, extension = recover_image(source)
    for number in range(1, 10000):
        suffix = "" if number == 1 else f" ({number})"
        target = destination / f"{source.stem}-recuperee{suffix}{extension}"
        if target.is_file() and target.stat().st_size == len(data) and target.read_bytes() == data:
            return str(target)
        if _reserve(target):
            try:
                _publish(target.parent, target, lambda stream: stream.write(data))
            except BaseException:
                target.unlink(missing_ok=True)
                raise
            return str(target)
    raise OSError("Impossible de réserver un nom pour la photo récupérée.")


def recovery_job(store, profile, paths, destination):
    paths = list(dict.fromkeys(paths))
    known = {row["path"] for row in store.quarantined(profile)}
    if not paths or not known.issuperset(paths):
        raise ValueError("Choisissez des photos mises à l’écart dans ce profil.")
    return store.new_job(profile, "recovery", {"paths": paths, "destination": str(Path(destination).resolve()),
                                               "outputs": [], "errors": []})


def export_one(row, destination):
    """Identical copy of a kept photo and its sidecars, never overwriting a file.

    The original name is kept when free, otherwise `` (2)``, `` (3)``… is added.
    Names are reserved exclusively, written through a same-volume temporary
    file, and the copy is checked against the digest measured at import.
    """
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    source = Path(row["path"])
    if digest(source) != row["data"]["digest"]:
        raise ValueError("L’original a changé depuis son analyse : réimportez-le.")
    # Ending of each sidecar after the photo stem: ".xmp" or ".nef.xmp".
    sidecars = {path: path.name[len(source.stem):] for path in companions(source)}
    reserved = []
    try:
        for number in range(1, 100000):
            stem = source.stem if number == 1 else f"{source.stem} ({number})"
            candidate = destination / (stem + source.suffix)
            if not _reserve(candidate):
                continue
            reserved.append(candidate)
            for ending in sidecars.values():
                target = destination / (stem + ending)
                if not _reserve(target):
                    break
                reserved.append(target)
            else:
                break
            for path in reserved:
                path.unlink()
            reserved.clear()
        if not reserved:
            raise OSError("Impossible de réserver un nom d’export")

        def copy(stream, path=source):
            with open(path, "rb") as original:
                shutil.copyfileobj(original, stream, 1024 * 1024)
        _publish(destination, reserved[0], copy)
        if digest(reserved[0]) != row["data"]["digest"]:
            raise OSError("La copie ne correspond pas à l’original.")
        for path, target in zip(sidecars, reserved[1:], strict=True):
            _publish(destination, target, lambda stream, p=path: copy(stream, p))
        return str(reserved[0])
    except BaseException:
        for path in reserved:
            path.unlink(missing_ok=True)
        raise


def prepare_photo(path, encoder, training=False):
    """CPU/IO work only: database writes remain ordered in the job process."""
    checksum = None if training else digest(path)
    image = decode(path)
    return {"image": image, "features": features(image),
            "embedding": encoder.encode(image), "digest": checksum,
            "time": capture_time(path)}


def run_job(root, identifier, events, cancel, encoder_factory=DinoEncoder, preparation_workers=None, load=None):
    """``preparation_workers`` None sizes the work to this computer and ``load``
    (a mode name or a shared index the interface may change while it runs)."""
    store = Store(root)
    pool = None
    try:
        job = store.job(identifier)
        if job["state"] in ("done", "superseded"):
            events.put({"type": "done", "job": identifier})
            return
        store.update_job(identifier, state="running", error="")
        payload, profile, kind = job["payload"], job["profile"], job["kind"]
        if kind == "training" and job["state"] == "failed" and payload.get("errors"):
            # A failed catalog update may already be at the final cursor. Revisit
            # failed sources on resume; successful samples and references are cached.
            payload["errors"] = []
            job["cursor"] = 0
            store.update_job(identifier, cursor=0, payload=payload)
        if kind == "selection":
            _run_selection(store, identifier, payload, events, cancel)
            return
        if kind == "export" and (payload.get("replace") or not payload.get("destination")):
            # Written by a version that could replace originals by retouched copies.
            raise ValueError("Cette tâche d’export d’une version précédente n’est plus prise en charge : "
                             "supprimez-la dans « Gérer les tâches » et exportez à nouveau.")
        needs_encoder = kind == "analysis" or (kind == "training" and bool(payload["items"]))
        mode = performance.read_mode(load)
        current = performance.plan(mode)
        if load is not None:
            performance.lower_priority(mode)
        if preparation_workers is not None:
            # Fixed by the caller (tests, diagnostics): no automatic sizing.
            current = performance.Plan(mode, preparation_workers, current.threads, current.modest)
        if needs_encoder:
            encoder = (encoder_factory(threads=current.threads) if encoder_factory is DinoEncoder
                       else encoder_factory())
        else:
            encoder = None
        snapshot = None
        if kind == "analysis":
            if not payload["batch"]:
                snapshot = store.snapshot(profile, encoder.version)
                if any(r.get("model") != encoder.version for r in snapshot["references"]):
                    raise ValueError("Le modèle des références a changé. Réimportez les références dans un nouveau profil.")
                batch_name = Path(payload["paths"][0]).parent.name if payload["paths"] else "Lot"
                payload["batch"] = store.create_batch(profile, batch_name, snapshot, payload["selectivity"])
                store.update_job(identifier, payload=payload)
            else:
                snapshot = store.batch(payload["batch"])["snapshot"]
                if snapshot["model"] != encoder.version:
                    raise ValueError("Ce lot nécessite la version du modèle utilisée à sa création.")
        items = payload["items"] if kind in ("export", "training") else payload["paths"]
        pending = {}
        moved = {entry["from"] for entry in payload.get("quarantined", [])}

        def set_aside(path, exc, owner=None, role=None):
            """Corrupt RAW: out of its folder and of the profile catalog, task continues."""
            target = quarantine(path)
            entry = {"file": Path(path).name, "from": str(path), "to": target, "error": str(exc)}
            payload.setdefault("quarantined", []).append(entry)
            moved.add(str(path))
            if owner:
                store.forget_source(profile, owner, role, path)
            store.save_quarantine(identifier, profile, entry, payload)
            return target
        # The fastest load bounds the pool; the current load bounds the window,
        # so the user can lower or raise it while the task runs.
        largest = (preparation_workers if preparation_workers is not None
                   else max(current.workers, performance.plan("fast").workers))
        if kind in ("analysis", "training") and largest:
            # Bound decoded photos in memory; never enqueue a whole reportage.
            pool = ThreadPoolExecutor(max_workers=largest)

        def prepare(index):
            item = items[index]
            if kind == "training" and item["role"] == "reference":
                return prepare_reference(item["path"], encoder)
            path = item["path"] if kind == "training" else item
            return prepare_photo(path, encoder, kind == "training")

        def wanted(index):
            """Whether the job loop will ask for this photo (checked in the job thread)."""
            item = items[index]
            if kind == "analysis":
                return item not in moved and not store.db.execute(
                    "SELECT 1 FROM photos WHERE batch=? AND path=?", (payload["batch"], item)).fetchone()
            if item["path"] in moved:
                return False
            if item["role"] == "reference":
                return not store.has_reference(item["reportage"], item["path"])
            return not store.has_training(profile, item["reportage"], item["role"], item["path"])

        def prepared(index):
            if pool is None or current.workers <= 0:
                return prepare(index)
            # Queue at most one window of photos ahead. Exceptions are observed in
            # input order so errors and resumable cursors match sequential processing.
            if index not in pending:
                pending[index] = pool.submit(prepare, index)
            next_index = index + 1
            while (len(pending) < current.workers and next_index < len(items)
                   and next_index < index + 4 * current.workers):
                if next_index not in pending and wanted(next_index):
                    pending[next_index] = pool.submit(prepare, next_index)
                next_index += 1
            return pending.pop(index).result()

        estimator = ProgressEstimator()
        for index in range(job["cursor"], len(items)):
            if load is not None and not isinstance(load, str):
                mode = performance.read_mode(load)
                if mode != current.mode:
                    current = performance.plan(mode)
                    performance.lower_priority(mode)
                    if hasattr(encoder, "set_threads"):
                        encoder.set_threads(current.threads)
            if cancel.is_set():
                if kind == "analysis":
                    events.put({"type": "phase", "label": "Tri des photos déjà analysées…"})
                    rows = reselect(store.photos(payload["batch"]), snapshot, payload["selectivity"])
                    store.save_photos(rows)
                store.update_job(identifier, state="paused")
                events.put({"type": "paused", "job": identifier})
                return
            item = items[index]
            label = Path(item["path"] if isinstance(item, dict) else item).name
            known_errors = len(payload.get("errors", []))
            events.put({"type": "progress", "current": index, "total": len(items), "label": label,
                        "remaining_seconds": estimator.update(index, len(items))})
            try:
                if kind == "recovery":
                    output, error = None, None
                    try:
                        output = recover_one(item, payload["destination"])
                        payload["outputs"].append(output)
                    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError) as exc:
                        error = str(exc)
                        payload["errors"].append({"file": label, "error": error})
                    with store.db:
                        store.db.execute("UPDATE quarantine SET output=COALESCE(?,output),error=? WHERE profile=? AND path=?",
                                         (output, error, profile, item))
                        store.db.execute("UPDATE jobs SET cursor=?,payload=? WHERE id=?", (index + 1, pack(payload), identifier))
                    continue
                elif kind == "export":
                    payload["outputs"].append(export_one(item, payload["destination"]))
                elif kind == "training":
                    reportage = item["reportage"]
                    if item["path"] in moved:
                        # Same file listed in the rush and the kept photos.
                        store.forget_source(profile, reportage, item["role"], item["path"])
                    elif item["role"] == "reference":
                        _save_reference(store, profile, item["path"], encoder, reportage,
                                        lambda i=index: prepared(i))
                    elif not store.has_training(profile, reportage, item["role"], item["path"]):
                        _save_training_photo(store, profile, reportage, item, prepared(index), encoder.version)
                elif kind == "analysis":
                    batch_id = payload["batch"]
                    existing = store.db.execute("SELECT id FROM photos WHERE batch=? AND path=?", (batch_id, item)).fetchone()
                    if not existing and item not in moved:
                        photo_id = uid()
                        source = item
                        try:
                            photo = prepared(index)
                            image, stats, embedding = photo["image"], photo["features"], photo["embedding"]
                            data = propose(stats, embedding, snapshot, payload["selectivity"])
                            data.update({"digest": photo["digest"], "features": stats, "embedding": embedding,
                                         "time": photo["time"]})
                            proxy = store.private_dir(profile, "batches", batch_id) / f"{photo_id}.png"
                            # Fast PNG compression: proxies are private caches.
                            image.save(proxy, compress_level=1)
                            thumb = image.copy()
                            thumb.thumbnail((240, 180))
                            thumb.save(proxy.with_suffix(".jpg"), quality=85)
                        except CorruptPhoto as exc:
                            target = set_aside(item, exc)
                            source = target or item
                            message = (f"Photo déplacée dans « {QUARANTINE_DIR} »" if target
                                       else "Photo mise à l’écart dans l’application (déplacement impossible)")
                            data = {"error": f"{message} : {exc}", "decision": "error", "proposed": "error"}
                        except (ValueError, RuntimeError) as exc:
                            data = {"error": str(exc), "decision": "error", "proposed": "error"}
                        store.save_photo(photo_id, batch_id, source, data)
                else:
                    raise ValueError("Type de tâche inconnu")
            except OSError:
                # Disk, missing-source, permission errors must remain resumable.
                raise
            except (ValueError, RuntimeError) as exc:
                if isinstance(exc, CorruptPhoto) and kind == "training":
                    set_aside(item["path"], exc, item["reportage"], item["role"])
                else:
                    error = {"file": label, "error": str(exc)}
                    if kind == "training":
                        error["reportage"] = item["reportage"]
                    payload.setdefault("errors", []).append(error)
            pending.pop(index, None)
            if kind == "analysis" or (kind == "training" and len(payload.get("errors", [])) == known_errors):
                # Only the cursor: rewriting long path lists for every photo is wasteful.
                store.update_job(identifier, cursor=index + 1)
            else:
                store.update_job(identifier, cursor=index + 1, payload=payload)
        if kind in ("analysis", "training"):
            label = "Finalisation du tri…" if kind == "analysis" else "Calcul du profil de tri…"
            events.put({"type": "phase", "label": label})
        if kind == "analysis":
            # Atomic scene selection: no half-decided batches after an interruption.
            # Rebuild technical proposals too: a paused import may already have
            # scene decisions, which must not become technical doubts on resume.
            rows = reselect(store.photos(payload["batch"]), snapshot, payload["selectivity"])
            store.save_photos(rows)
        if kind == "training":
            _finish_training(store, identifier, profile, payload, encoder.version if encoder else None)
        else:
            store.update_job(identifier, state="done", payload=payload)
        events.put({"type": "done", "job": identifier, "total": len(items)})
    except BaseException as exc:  # noqa: BLE001 - worker boundary must report all failures to the UI
        store.update_job(identifier, state="failed", error=f"{type(exc).__name__}: {exc}")
        events.put({"type": "error", "message": str(exc), "job": identifier})
    finally:
        if pool is not None:
            pool.shutdown(wait=True, cancel_futures=True)
        store.close()

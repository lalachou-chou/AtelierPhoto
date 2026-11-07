import io
import os
import queue
import shutil
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from . import look as looks
from .analysis import propose, reselect
from .config import QUARANTINE_DIR, RAW_EXTENSIONS
from .dino import DinoEncoder
from .imaging import (
    IDENTITY_RECIPE,
    IDENTITY_STYLE,
    SRGB,
    CorruptPhoto,
    as_image,
    capture_time,
    decode,
    digest,
    features,
    render,
)
from .progress import ProgressEstimator
from .store import Store, pack, uid
from .training import learn
from .xmp import sidecar

FORMATS = ("JPEG", "PNG", "RAW")


def decode_for_analysis(path):
    try:
        return decode(path, preview=True)
    except OSError as exc:
        if exc.errno is not None:
            raise
        raise ValueError(f"Photo illisible : {exc}") from exc


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
        # Same volume; never overwrite an earlier quarantined file.
        os.rename(source, target)
    except PermissionError:
        return None
    for extension in (".xmp", ".XMP"):
        companion = source.with_suffix(extension)
        if companion.is_file():
            try:
                if not target.with_suffix(extension).exists():
                    os.rename(companion, target.with_suffix(extension))
            except OSError:
                pass
            break
    return str(target)


def reference_job(store, profile, paths):
    return store.new_job(profile, "references", {"paths": paths, "errors": []})


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
        if not paths["rush"] or not paths["kept"]:
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
            if not paths:
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


def _save_reference(store, profile, path, encoder, group=None):
    if group and store.has_reference(group, path):
        return
    checksum = digest(path)
    existing = store.db.execute("SELECT id FROM refs WHERE profile=? AND digest=?", (profile, checksum)).fetchone()
    if existing:
        if group:
            store.link_reference(profile, group, existing["id"], path)
        return
    pixels, _ = decode_for_analysis(path)
    image = as_image(pixels)
    data = {"features": features(pixels), "embedding": encoder.encode(image), "model": encoder.version}
    ref_id = uid()
    proxy = store.private_dir(profile, "references") / f"{ref_id}.png"
    image.save(proxy, compress_level=1)
    if not store.add_reference(profile, ref_id, checksum, Path(path).name, data, group=group, path=path):
        proxy.unlink(missing_ok=True)


def _save_training_photo(store, profile, reportage, item, photo, encoder_version):
    data = {"name": Path(item["path"]).name, "stats": photo["features"], "embedding": photo["embedding"],
            "time": photo["time"], "model": encoder_version}
    sample_id = uid()
    np.save(store.private_dir(profile, "training", reportage) / f"{sample_id}.npy",
            photo["sample"].astype(np.float16))
    store.add_training(sample_id, profile, reportage, item["role"], item["path"], data)


def _finish_training(store, identifier, profile, payload, encoder_version):
    def load(row):
        path = store.private_dir(profile, "training", row["reportage"]) / f"{row['id']}.npy"
        try:
            return np.load(path, allow_pickle=False) if path.exists() else None
        except ValueError as exc:
            raise RuntimeError("Un échantillon enregistré est illisible : retirez puis ajoutez à nouveau ce reportage.") from exc

    if "selected_reportages" in payload:
        selected = set(payload["selected_reportages"])
        if payload.get("errors"):
            raise ValueError("Certains fichiers sont illisibles : le profil précédent est conservé. Corrigez-les ou retirez les reportages concernés.")
        rows = [r for r in store.training(profile) if r["reportage"] in selected]
        if selected:
            try:
                model, warnings = learn(rows, load, encoder_version)
            except ValueError as exc:
                # A removal must never leave the removed examples in the model,
                # even when the remaining set is too small to train on its own.
                model = None
                warnings = [str(exc), "Sélection et filtre par défaut utilisés jusqu’à l’ajout de reportages exploitables."]
        else:
            model, warnings = None, []
        payload["warnings"] = warnings
        payload["summary"] = {k: (model or {}).get(k, 0) for k in ("reportages", "photos", "kept", "pairs")}
        payload["summary"]["reference_groups"] = len(payload.get("selected_reference_groups", []))
        store.complete_training(identifier, model, payload)
        return

    rows = store.training(profile, completed_only=True, include_job=identifier)
    current = {r["id"] for r in payload.get("reportages", [])}
    if payload.get("reportage"):
        current.add(payload["reportage"])
    if not any(row["reportage"] in current for row in rows):
        raise ValueError("Aucun nouveau reportage complet exploitable. Vérifiez les fichiers indiqués en erreur.")
    model, warnings = learn(rows, load, encoder_version)
    if payload.get("errors"):
        warnings.append("Les reportages contenant des fichiers illisibles ont été exclus de l’apprentissage.")
    payload["warnings"] = warnings
    payload["summary"] = {k: model.get(k) for k in ("reportages", "photos", "kept", "pairs")}
    store.complete_training(identifier, model, payload)


def export_job(store, batch, destination, format="JPEG"):
    if format not in FORMATS:
        raise ValueError("Format d’export invalide")
    if not store.batch_ready(batch):
        raise ValueError("Terminez l’analyse ou le tri du lot avant l’export.")
    photos = store.photos(batch)
    items = [r for r in photos if "error" not in r["data"] and r["data"]["decision"] == "keep"]
    if not items:
        raise ValueError("Aucune photo retenue à exporter.")
    if any(not r["data"].get("validated") for r in photos if "error" not in r["data"]):
        raise ValueError("Validez les propositions avant de les exporter.")
    record = store.batch(batch)
    return store.new_job(record["profile"], "export", {
        "batch": batch, "filter": record["filter_enabled"], "look": record["snapshot"].get("look"),
        "items": [{"id": r["id"], "path": r["path"], "data": {k: r["data"][k] for k in ("digest", "recipe", "style")}} for r in items],
        "destination": str(Path(destination).resolve()), "format": format, "outputs": [], "errors": []})


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
        with os.fdopen(fd, "wb") as stream:
            write(stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def export_one(row, destination, format, enabled=True, look=None):
    """Exclusive filename reservation, same-volume atomic publish, immutable source.

    ``RAW`` copies RAW originals bit for bit with an XMP sidecar holding the
    correction; JPEG/PNG sources of the batch are rendered as JPEG instead.
    ``enabled=False`` exports without the applied filter.
    """
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    source = Path(row["path"])
    if digest(source) != row["data"]["digest"]:
        raise ValueError("L’original a changé depuis son analyse : réimportez-le.")
    recipe, style = (row["data"]["recipe"], row["data"]["style"]) if enabled else (IDENTITY_RECIPE, IDENTITY_STYLE)
    raw_copy = format == "RAW" and source.suffix.lower() in RAW_EXTENSIONS
    if format == "RAW" and not raw_copy:
        format = "JPEG"
    suffix = source.suffix if raw_copy else ".jpg" if format == "JPEG" else ".png"
    stem = f"{source.stem[:120]}_Atelier"
    reserved = []
    try:
        for number in range(1, 100000):
            candidate = destination / f"{stem}_{number:03}{suffix}"
            if not _reserve(candidate):
                continue
            reserved.append(candidate)
            if not raw_copy:
                break
            # Editors pair a RAW with the sidecar of the same base name.
            if _reserve(candidate.with_suffix(".xmp")):
                reserved.append(candidate.with_suffix(".xmp"))
                break
            reserved.pop().unlink(missing_ok=True)
        if not reserved:
            raise OSError("Impossible de réserver un nom d’export")
        if raw_copy:
            def copy(stream):
                with open(source, "rb") as original:
                    shutil.copyfileobj(original, stream, 1024 * 1024)
            _publish(destination, reserved[0], copy)
            if digest(reserved[0]) != row["data"]["digest"]:
                raise OSError("La copie RAW ne correspond pas à l’original.")
            xmp = sidecar(recipe, style, enabled)
            _publish(destination, reserved[1], lambda stream: stream.write(xmp))
        else:
            pixels, metadata = decode(source)
            image = render(pixels, recipe, style, look if enabled else None)
            _publish(destination, reserved[0], lambda stream: image.save(
                stream, format=format, icc_profile=SRGB, **metadata,
                **({"quality": 95, "subsampling": 0} if format == "JPEG" else {})))
        return str(reserved[0])
    except BaseException:
        for path in reserved:
            path.unlink(missing_ok=True)
        raise


def prepare_photo(path, encoder, training=False, with_look=False):
    """CPU/IO work only: database writes remain ordered in the job process."""
    checksum = None if training else digest(path)
    pixels, _ = decode_for_analysis(path)
    image = as_image(pixels)
    return {"image": image, "features": features(pixels),
            "embedding": encoder.encode(image), "digest": checksum,
            "time": capture_time(path),
            "sample": looks.sample(pixels) if training or with_look else None}


def run_job(root, identifier, events, cancel, encoder_factory=DinoEncoder, preparation_workers=2):
    store = Store(root)
    pool = None
    try:
        job = store.job(identifier)
        if job["state"] in ("done", "superseded"):
            events.put({"type": "done", "job": identifier})
            return
        store.update_job(identifier, state="running", error="")
        payload, profile, kind = job["payload"], job["profile"], job["kind"]
        if kind == "selection":
            _run_selection(store, identifier, payload, events, cancel)
            return
        needs_encoder = kind in ("references", "analysis") or (kind == "training" and bool(payload["items"]))
        encoder = encoder_factory() if needs_encoder else None
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
            payload.setdefault("quarantined", []).append(
                {"file": Path(path).name, "from": str(path), "to": target, "error": str(exc)})
            moved.add(str(path))
            if owner:
                store.forget_source(profile, owner, role, path)
            store.update_job(identifier, payload=payload)
            return target
        if kind in ("analysis", "training") and preparation_workers:
            # Bound decoded photos in memory; never enqueue a whole reportage.
            pool = ThreadPoolExecutor(max_workers=preparation_workers)

        def prepare(index):
            item = items[index]
            path = item["path"] if kind == "training" else item
            return prepare_photo(path, encoder, kind == "training", bool(snapshot and snapshot.get("look")))

        def prepared(index):
            if pool is None:
                return prepare(index)
            # Queue at most two photos ahead. Exceptions are observed in input
            # order so errors and resumable cursors retain their old semantics.
            for next_index in range(index, min(index + preparation_workers, len(items))):
                if kind == "training" and items[next_index]["role"] == "reference":
                    continue
                if next_index not in pending:
                    pending[next_index] = pool.submit(prepare, next_index)
            return pending.pop(index).result()

        estimator = ProgressEstimator()
        for index in range(job["cursor"], len(items)):
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
                if kind == "export":
                    output = export_one(item, payload["destination"], payload["format"], payload.get("filter", True), payload.get("look"))
                    payload["outputs"].append(output)
                elif kind == "references":
                    if item not in moved:
                        _save_reference(store, profile, item, encoder)
                elif kind == "training":
                    reportage = item.get("reportage", payload.get("reportage"))
                    if item["path"] in moved:
                        # Same file listed in the rush and the kept photos.
                        store.forget_source(profile, reportage, item["role"], item["path"])
                    elif item["role"] == "reference":
                        _save_reference(store, profile, item["path"], encoder, reportage)
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
                            data = propose(stats, embedding, snapshot, payload["selectivity"], photo["sample"])
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
                            message = (f"RAW corrompu, déplacé dans « {QUARANTINE_DIR} »" if target
                                       else "RAW corrompu, ignoré (dossier en lecture seule)")
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
                if isinstance(exc, CorruptPhoto) and kind in ("training", "references"):
                    path = item["path"] if kind == "training" else item
                    owner = item.get("reportage", payload.get("reportage")) if kind == "training" else None
                    set_aside(path, exc, owner, item["role"] if kind == "training" else None)
                else:
                    error = {"file": label, "error": str(exc)}
                    if kind == "training":
                        error["reportage"] = item.get("reportage", payload.get("reportage"))
                    payload.setdefault("errors", []).append(error)
            pending.pop(index, None)
            if kind == "analysis" or (kind == "training" and len(payload.get("errors", [])) == known_errors):
                # Only the cursor: rewriting long path lists for every photo is wasteful.
                store.update_job(identifier, cursor=index + 1)
            else:
                store.update_job(identifier, cursor=index + 1, payload=payload)
        if kind in ("analysis", "training"):
            label = "Finalisation du tri…" if kind == "analysis" else "Calcul du profil et de la retouche…"
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


def preview_worker(input_queue, output_queue):
    """Separate process for decoding/rendering previews; newest request wins."""
    from PIL import Image
    cached = (None, None)
    while True:
        task = input_queue.get()
        if task is None:
            return
        try:
            while True:
                newer = input_queue.get_nowait()
                if newer is None:
                    return
                task = newer
        except queue.Empty:
            pass
        try:
            # Slider moves re-render the same photo: decode it only once.
            if cached[0] != task["path"]:
                with Image.open(task["path"]) as image:
                    image.thumbnail((1100, 850))
                    cached = (task["path"], np.asarray(image.convert("RGB"), dtype=np.float32) / 255)
            pixels = cached[1]
            image = as_image(pixels) if task["before"] else render(pixels, task["recipe"], task["style"], task.get("look"))
            buffer = io.BytesIO()
            image.save(buffer, format="PNG", compress_level=1)
            output_queue.put({"token": task["token"], "bytes": buffer.getvalue()})
        except Exception as exc:  # noqa: BLE001 - preview worker reports failures across processes
            output_queue.put({"token": task["token"], "error": str(exc)})

import io
import os
import queue
import shutil
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from . import look as looks
from .analysis import finalize, propose
from .dino import DinoEncoder
from .config import RAW_EXTENSIONS
from .imaging import (
    IDENTITY_RECIPE,
    IDENTITY_STYLE,
    SRGB,
    as_image,
    capture_time,
    decode,
    digest,
    features,
    render,
)
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


def reference_job(store, profile, paths):
    return store.new_job(profile, "references", {"paths": paths, "errors": []})


def analysis_job(store, profile, paths, selectivity=.5):
    return store.new_job(profile, "analysis", {"paths": paths, "selectivity": selectivity, "batch": None})


def training_job(store, profile, rush, kept, name="Reportage"):
    """Teach the profile with a sorted reportage: complete rush + delivered photos."""
    if not rush or not kept:
        raise ValueError("Choisissez le dossier du rush complet et celui des photos retenues.")
    kept_set = set(kept)
    items = [{"role": "rush", "path": p} for p in rush if p not in kept_set] + [{"role": "kept", "path": p} for p in kept]
    return store.new_job(profile, "training", {"reportage": uid(), "name": name, "items": items, "errors": [], "warnings": []})


def export_job(store, batch, destination, format="JPEG"):
    if format not in FORMATS:
        raise ValueError("Format d’export invalide")
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
        if job["state"] == "done":
            events.put({"type": "done", "job": identifier})
            return
        store.update_job(identifier, state="running", error="")
        payload, profile, kind = job["payload"], job["profile"], job["kind"]
        encoder = encoder_factory() if kind in ("references", "analysis", "training") else None
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
                if next_index not in pending:
                    pending[next_index] = pool.submit(prepare, next_index)
            return pending.pop(index).result()

        for index in range(job["cursor"], len(items)):
            if cancel.is_set():
                store.update_job(identifier, state="paused")
                events.put({"type": "paused", "job": identifier})
                return
            item = items[index]
            label = Path(item["path"] if isinstance(item, dict) else item).name
            known_errors = len(payload.get("errors", []))
            events.put({"type": "progress", "current": index, "total": len(items), "label": label})
            try:
                if kind == "export":
                    output = export_one(item, payload["destination"], payload["format"], payload.get("filter", True), payload.get("look"))
                    payload["outputs"].append(output)
                elif kind == "references":
                    checksum = digest(item)
                    existing = store.db.execute("SELECT id FROM refs WHERE profile=? AND digest=?", (profile, checksum)).fetchone()
                    if not existing:
                        pixels, _ = decode_for_analysis(item)
                        image = as_image(pixels)
                        data = {"features": features(pixels), "embedding": encoder.encode(image), "model": encoder.version}
                        ref_id = uid()
                        path = store.private_dir(profile, "references") / f"{ref_id}.png"
                        image.save(path, compress_level=1)
                        if not store.add_reference(profile, ref_id, checksum, label, data):
                            path.unlink(missing_ok=True)
                elif kind == "training":
                    reportage = payload["reportage"]
                    if not store.has_training(profile, reportage, item["role"], item["path"]):
                        photo = prepared(index)
                        data = {"name": label, "stats": photo["features"], "embedding": photo["embedding"],
                                "time": photo["time"], "model": encoder.version}
                        sample_id = uid()
                        np.save(store.private_dir(profile, "training", reportage) / f"{sample_id}.npy",
                                photo["sample"].astype(np.float16))
                        store.add_training(sample_id, profile, reportage, item["role"], item["path"], data)
                elif kind == "analysis":
                    batch_id = payload["batch"]
                    existing = store.db.execute("SELECT id FROM photos WHERE batch=? AND path=?", (batch_id, item)).fetchone()
                    if not existing:
                        photo_id = uid()
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
                        except (ValueError, RuntimeError) as exc:
                            data = {"error": str(exc), "decision": "error", "proposed": "error"}
                        store.save_photo(photo_id, batch_id, item, data)
                else:
                    raise ValueError("Type de tâche inconnu")
            except OSError:
                # Disk, missing-source, permission errors must remain resumable.
                raise
            except (ValueError, RuntimeError) as exc:
                payload.setdefault("errors", []).append({"file": label, "error": str(exc)})
            pending.pop(index, None)
            if kind == "analysis" or (kind == "training" and len(payload.get("errors", [])) == known_errors):
                # Only the cursor: rewriting long path lists for every photo is wasteful.
                store.update_job(identifier, cursor=index + 1)
            else:
                store.update_job(identifier, cursor=index + 1, payload=payload)
        if kind == "analysis":
            # Atomic scene selection: no half-decided batches after an interruption.
            rows = finalize(store.photos(payload["batch"]), snapshot, payload["selectivity"])
            with store.atomic():
                for row in rows:
                    store.db.execute("UPDATE photos SET data=? WHERE id=?", (pack(row["data"]), row["id"]))
        if kind == "training":
            def load(row):
                path = store.private_dir(profile, "training", row["reportage"]) / f"{row['id']}.npy"
                return np.load(path) if path.exists() else None
            model, warnings = learn(store.training(profile), load, encoder.version)
            store.set_model(profile, model)
            payload["warnings"] = warnings
            payload["summary"] = {k: model.get(k) for k in ("reportages", "photos", "kept", "pairs")}
        store.update_job(identifier, state="done", payload=payload)
        events.put({"type": "done", "job": identifier, "total": len(items)})
    except BaseException as exc:  # noqa: BLE001 - worker boundary must report all failures to the UI
        store.update_job(identifier, state="failed", error=f"{type(exc).__name__}: {exc}")
        events.put({"type": "error", "message": str(exc), "job": identifier})
    finally:
        if pool is not None:
            pool.shutdown(wait=True, cancel_futures=True)
        store.close()


def preview_worker(root, input_queue, output_queue):
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

import io
import os
import queue
import shutil
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from PIL import Image, JpegImagePlugin

from . import lightroom, performance
from . import local as local_edits
from . import look as looks
from . import tools as advanced
from .analysis import propose, reselect
from .config import QUARANTINE_DIR, RAW_EXTENSIONS
from .dino import DinoEncoder
from .imaging import (
    SRGB,
    CorruptPhoto,
    active_crop,
    active_recipe,
    as_image,
    capture_time,
    cropped_pixels,
    decode,
    digest,
    effective,
    features,
    look_strength,
    render,
    render_pixels,
)
from .progress import ProgressEstimator
from .recovery import recover_image
from .store import Store, pack, uid
from .training import learn
from .xmp import (
    apply_tones,
    development,
    find_sidecar,
    raw_crop,
    read_settings,
    sidecar,
)

FORMATS = ("JPEG", "PNG", "TIFF", "RAW", "SOURCE")


def decode_for_analysis(path):
    try:
        return decode(path, preview=True)
    except (OSError, SyntaxError) as exc:
        if isinstance(exc, OSError) and exc.errno is not None and exc.errno >= 0:
            raise
        source = Path(path)
        if source.suffix.lower() in (".jpeg", ".jpg", ".png"):
            with source.open("rb") as stream:
                header = stream.read(8)
            if header.startswith(b"\xff\xd8\xff") or header == b"\x89PNG\r\n\x1a\n":
                raise CorruptPhoto(f"Photo endommagée ou incomplète : {exc}") from exc
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


def reference_digest(path):
    xmp_path = find_sidecar(path)
    checksum = digest(path)
    if xmp_path:
        # A changed sidecar is a different reference.
        checksum += ":xmp:" + digest(xmp_path)
    return checksum, xmp_path


def prepare_reference(path, encoder, identity=None):
    """CPU/IO work for one reference; the database stays in the job thread."""
    checksum, xmp_path = identity or reference_digest(path)
    pixels, _ = decode_for_analysis(path)
    raw = Path(path).suffix.lower() in RAW_EXTENSIONS
    data = {"source": "raw" if raw else "image"}
    if xmp_path:
        developed = development(read_settings(xmp_path), path)
        pixels = cropped_pixels(pixels, developed["crop"])
        before = features(pixels)
        recipe = {"intensity": 1., "exposure": 0., "temperature": 0., "contrast": 0., "saturation": 0.}
        pixels = render_pixels(pixels, recipe, developed["style"], bit_depth=16,
                               tools=developed.get("tools")).astype(np.float32) / 65535
        pixels = apply_tones(pixels, developed["tones"])
        # Relative target: the sidecar edit transfers to new photos as a change.
        data.update(source=data["source"] + "+xmp", before=before, ignored=developed["ignored"])
    elif raw:
        # An undeveloped RAW shows resemblance and framing, not the delivered look.
        data["render"] = False
    image = as_image(pixels)
    stats = features(pixels)
    data.update(features=stats, embedding=encoder.encode(image), model=encoder.version)
    if xmp_path:
        data["after"] = stats
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
        identity = reference_digest(path)
        checksum = identity[0]
    existing = store.db.execute("SELECT id FROM refs WHERE profile=? AND digest=?", (profile, checksum)).fetchone()
    if existing:
        store.link_reference(profile, group, existing["id"], path)
        return
    if reference is None:
        reference = prepare_reference(path, encoder, identity)
    ref_id = uid()
    proxy = store.private_dir(profile, "references") / f"{ref_id}.png"
    reference["image"].save(proxy, compress_level=1)
    if not store.add_reference(profile, ref_id, checksum, Path(path).name, reference["data"], group=group, path=path):
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
        payload["summary"] = {k: (model or {}).get(k, 0) for k in ("reportages", "photos", "kept", "pairs", "crops")}
        payload["summary"]["examples"] = len((model or {}).get("examples", []))
        payload["summary"]["reference_groups"] = len(payload.get("selected_reference_groups", []))
        store.complete_training(identifier, model, payload)
        return

    rows = store.training(profile, completed_only=True, include_job=identifier)
    current = {r["id"] for r in payload["reportages"]}
    if not any(row["reportage"] in current for row in rows):
        raise ValueError("Aucun nouveau reportage complet exploitable. Vérifiez les fichiers indiqués en erreur.")
    model, warnings = learn(rows, load, encoder_version)
    if payload.get("errors"):
        warnings.append("Les reportages contenant des fichiers illisibles ont été exclus de l’apprentissage.")
    payload["warnings"] = warnings
    payload["summary"] = {k: model.get(k) for k in ("reportages", "photos", "kept", "pairs", "crops")}
    payload["summary"]["examples"] = len(model.get("examples", []))
    store.complete_training(identifier, model, payload)


def check_jpeg_quality(quality):
    if quality not in ("maximum", "source") and (type(quality) is not int or not 1 <= quality <= 100):
        raise ValueError("Choisissez la qualité source ou une qualité JPEG entre 1 et 100.")


def export_job(store, batch, destination, format="JPEG", quality="maximum", replace=False):
    check_jpeg_quality(quality)
    if format not in FORMATS:
        raise ValueError("Format d’export invalide")
    if replace and format == "SOURCE":
        raise ValueError("Une copie à l’identique ne peut pas remplacer les originaux.")
    if not store.batch_ready(batch):
        raise ValueError("Terminez l’analyse ou le tri du lot avant l’export.")
    photos = store.photos(batch)
    items = [r for r in photos if "error" not in r["data"] and r["data"]["decision"] == "keep"]
    if not items:
        raise ValueError("Aucune photo retenue à exporter.")
    if any(not r["data"].get("validated") for r in photos if "error" not in r["data"]):
        raise ValueError("Validez les propositions avant de les exporter.")
    if any(r["data"].get("replaced") for r in items):
        raise ValueError("Les originaux de ce lot ont déjà été remplacés par leur version retouchée. "
                         "Réimportez ces photos pour les exporter à nouveau.")
    record = store.batch(batch)
    export_items = []
    for row in items:
        # Everything export_one renders: global recipe, zone edits and advanced tools.
        data = {k: row["data"].get(k) for k in ("digest", "recipe", "manual_recipe", "style", "local_edits",
                                                 "tools", "initial_tools")}
        data["crop"] = active_crop(row["data"], record["crops_enabled"])
        export_items.append({"id": row["id"], "path": row["path"], "data": data})
    return store.new_job(record["profile"], "export", {
        "batch": batch, "filter": record["filter_enabled"], "look": record["snapshot"].get("look"),
        "items": export_items, "replace": bool(replace),
        "destination": "" if replace else str(Path(destination).resolve()),
        "format": format, "quality": quality, "outputs": [], "errors": []})


def _reserve(path):
    try:
        os.close(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
        return True
    except FileExistsError:
        return False


def _publish(destination, target, write):
    """Write through a same-volume temporary file, then replace our reservation."""
    fd, temporary = tempfile.mkstemp(prefix=".atelier-", suffix=".tmp", dir=destination)
    os.close(fd)
    try:
        # Reopen by path: writers such as tifffile read ``stream.name`` as a path.
        with open(temporary, "wb") as stream:
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


SAME_FORMAT = {"JPEG": (".jpg", ".jpeg"), "PNG": (".png",), "TIFF": (".tif", ".tiff")}


def _replace_original(source, format, suffix, raw_copy, write_xmp, copy_jpeg, build_xmp, write_render):
    """Replace the original by its retouched version, in its own folder.

    The new file is fully written and synced before the original disappears:
    an interruption leaves either the original or the result, never neither.
    """
    folder = source.parent
    if raw_copy:
        # The RAW stays untouched: only its Adobe-style sidecar is (re)written.
        if write_xmp:
            # Exact names: on case-insensitive volumes "x.xmp" also matches "x.XMP".
            names = set(os.listdir(folder))
            target = next((source.with_suffix(e) for e in (".xmp", ".XMP") if source.with_suffix(e).name in names),
                          source.with_suffix(".xmp"))
            xmp = build_xmp()
            _publish(folder, target, lambda stream: stream.write(xmp))
        return str(source)
    if copy_jpeg:
        return str(source)  # Nothing to change: the original already is the result.
    if source.suffix.lower() in SAME_FORMAT[format]:
        write_render(folder, source)  # Atomic same-name replacement.
        return str(source)
    target = source.with_suffix(suffix)
    number = 0
    while not _reserve(target):
        # Never overwrite another file, e.g. the camera JPEG of a RAW + JPEG pair.
        number += 1
        if number >= 100000:
            raise OSError("Impossible de réserver un nom pour la photo remplacée.")
        target = source.with_name(f"{source.stem[:120]}_Atelier_{number:03}{suffix}")
    try:
        write_render(folder, target)
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    source.unlink()
    return str(target)


def export_one(row, destination, format, enabled=True, look=None, quality="maximum", replace=False):
    """Exclusive filename reservation, same-volume atomic publish, immutable source.

    ``RAW`` copies RAW originals bit for bit with an XMP sidecar holding the
    correction. For other sources it uses the regular JPEG export.
    With the batch filter off, only edits made from the neutral starting point apply.
    ``replace`` writes the result next to the original and removes the original
    instead (see _replace_original); ``destination`` is then unused.
    """
    check_jpeg_quality(quality)
    if replace and format == "SOURCE":
        raise ValueError("Une copie à l’identique ne peut pas remplacer son original.")
    destination = Path(destination)
    if not replace:
        destination.mkdir(parents=True, exist_ok=True)
    source = Path(row["path"])
    if replace and not source.is_file():
        # E.g. resumed after an interruption that came right after this replacement.
        raise ValueError("Original introuvable : il a peut-être déjà été remplacé.")
    if digest(source) != row["data"]["digest"]:
        raise ValueError("L’original a changé depuis son analyse : réimportez-le.")
    data = row["data"]
    recipe = active_recipe(data, enabled)
    batch_filter = enabled
    enabled = enabled or bool(data.get("manual_recipe"))
    style = data["style"] if enabled else {}
    active_look = look if enabled else None
    crop = data.get("crop")
    if crop and tuple(crop) == (0, 0, 1, 1):
        crop = None
    # Zone edits are explicit photographer choices: they apply in both modes.
    local = local_edits.applied(data.get("local_edits"), batch_filter)
    tools = advanced.active(data, batch_filter)
    global_edits = any(effective(recipe, style).values())
    # Zone edits become Lightroom masks in the sidecar (see lightroom.py).
    raw_copy = format == "RAW" and source.suffix.lower() in RAW_EXTENSIONS
    write_xmp = raw_copy and (global_edits or bool(crop) or bool(local) or bool(tools))
    source_copy = format == "SOURCE"
    companions = {}
    if source_copy:
        # Adobe replaces the extension; darktable appends .xmp. Probe each naming
        # convention once, including on case-insensitive macOS volumes.
        for stem in (source.stem, source.name):
            for extension in (".xmp", ".XMP"):
                path = source.with_name(stem + extension)
                if path.is_file():
                    companions[path] = path.name[len(source.stem):]
                    break
    if format == "RAW" and not raw_copy:
        format = "JPEG"
    copy_jpeg = False
    automatic_quality = quality in ("maximum", "source")
    jpeg_options = {"quality": 100 if automatic_quality else quality, "subsampling": 0}
    if format == "JPEG" and source.suffix.lower() not in RAW_EXTENSIONS and automatic_quality:
        with Image.open(source) as original:
            if original.format == "JPEG":
                copy_jpeg = not (crop or global_edits or local or tools or look_strength(recipe, style, active_look))
                if quality == "source" and original.mode == "RGB" and original.quantization and not copy_jpeg:
                    sampling = JpegImagePlugin.get_sampling(original)
                    jpeg_options = {"qtables": original.quantization, "subsampling": max(0, sampling)}
    suffix = source.suffix if raw_copy or source_copy else {"JPEG": ".jpg", "PNG": ".png", "TIFF": ".tif"}[format]

    def build_xmp():
        flip = 0
        if crop or local:
            import rawpy
            with rawpy.imread(str(source)) as raw:
                flip = raw.sizes.flip
        masks = ""
        if local:
            small = None
            if any(z in lightroom.SAMPLED for e in local for z in e.get("zones") or ()):
                # Colour ranges are sampled on the developed, framed photo.
                preview, _ = decode(source, preview=True)
                small = render_pixels(local_edits.proxy(cropped_pixels(preview, crop)), recipe, style,
                                      active_look, tools=tools).astype(np.float32) / 65535
            masks = lightroom.corrections(local, crop=crop, flip=flip, small=small)
        return sidecar(recipe, style, enabled, crop=crop and raw_crop(crop, flip), tools=tools, masks=masks)

    def write_render(folder, target):
        pixels, metadata = decode(source)
        pixels = cropped_pixels(pixels, crop)
        if format == "TIFF":
            import tifffile

            pixels = render_pixels(pixels, recipe, style, active_look, local=local, tools=tools)
            # Uncompressed RGB16 needs no optional codecs and preserves every
            # rendered sample. Do not pass through Pillow's 8-bit RGB mode.
            _publish(folder, target, lambda stream: tifffile.imwrite(
                stream, pixels, photometric="rgb", metadata=None, iccprofile=SRGB,
                software="Atelier Photo", rowsperstrip=128))
        else:
            image = render(pixels, recipe, style, active_look, local=local, tools=tools)
            _publish(folder, target, lambda stream: image.save(
                stream, format=format, icc_profile=SRGB, **metadata,
                **(jpeg_options if format == "JPEG" else {})))

    if replace:
        return _replace_original(source, format, suffix, raw_copy, write_xmp, copy_jpeg, build_xmp, write_render)
    stem = f"{source.stem[:120]}_Atelier"
    reserved = []
    try:
        for number in range(1, 100000):
            candidate = destination / f"{stem}_{number:03}{suffix}"
            if raw_copy and any(candidate.with_name(base + ext).exists()
                                for base in (candidate.stem, candidate.name) for ext in (".xmp", ".XMP")):
                continue
            if not _reserve(candidate):
                continue
            reserved.append(candidate)
            sidecars = [".xmp"] if write_xmp else companions.values()
            for ending in sidecars:
                target = candidate.with_name(candidate.stem + ending)
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
        if raw_copy or source_copy or copy_jpeg:
            def copy(stream, path=source):
                with open(path, "rb") as original:
                    shutil.copyfileobj(original, stream, 1024 * 1024)
            _publish(destination, reserved[0], copy)
            if digest(reserved[0]) != row["data"]["digest"]:
                raise OSError("La copie ne correspond pas à l’original.")
            if write_xmp:
                xmp = build_xmp()
                _publish(destination, reserved[1], lambda stream: stream.write(xmp))
            else:
                for path, target in zip(companions, reserved[1:], strict=True):
                    _publish(destination, target, lambda stream, p=path: copy(stream, p))
        else:
            write_render(destination, reserved[0])
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
            return prepare_photo(path, encoder, kind == "training", bool(snapshot and snapshot.get("look")))

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
                    replace = payload.get("replace", False)
                    output = export_one(item, payload["destination"], payload["format"], payload["filter"],
                                        payload["look"], payload["quality"], replace=replace)
                    payload["outputs"].append(output)
                    if replace and (output != item["path"] or digest(output) != item["data"]["digest"]):
                        # The original is gone: block a second export that would retouch twice.
                        store.mark_replaced(item["id"], output)
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
            pixels = cropped_pixels(cached[1], task.get("crop"))
            image = as_image(pixels) if task["before"] else render(pixels, task["recipe"], task["style"], task.get("look"),
                                                                    local=task.get("local"), tools=task.get("tools"))
            buffer = io.BytesIO()
            image.save(buffer, format="PNG", compress_level=1)
            output_queue.put({"token": task["token"], "bytes": buffer.getvalue()})
        except Exception as exc:  # noqa: BLE001 - preview worker reports failures across processes
            output_queue.put({"token": task["token"], "error": str(exc)})

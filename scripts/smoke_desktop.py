"""Real DINOv3 + spawn processes + offscreen Qt integration, with a saved screenshot."""
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    import numpy as np
    from PIL import Image
    from PySide6.QtGui import QFontDatabase
    from PySide6.QtWidgets import QApplication

    from atelier.app import Window
    from atelier.pipeline import analysis_job, export_job, reference_job

    directory = ROOT / "test-output" / ("desktop-" + str(time.time_ns()))
    directory.mkdir(parents=True)
    paths = []
    generator = np.random.default_rng(42)
    yy, xx = np.mgrid[0:480, 0:640]
    for i in range(12):
        pixels = np.empty((480, 640, 3), dtype=np.uint8)
        for channel in range(3):
            pixels[:, :, channel] = np.clip(100 + 60 * np.sin(xx / (35 + i * 3) + channel) + 40 * np.cos(yy / 60 + i) + generator.normal(0, 3, (480, 640)), 0, 255)
        path = directory / f"Photo-test-{i + 1:02}.jpg"
        Image.fromarray(pixels).save(path, quality=95)
        paths.append(str(path))
    app = QApplication.instance() or QApplication([])
    if sys.platform == "win32" and os.environ.get("QT_QPA_PLATFORM") == "offscreen":
        for font in ("segoeui.ttf", "segoeuib.ttf"):
            identifier = QFontDatabase.addApplicationFont(str(Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / font))
            print(f"Offscreen font {font}: {identifier}")
    window = Window(directory / "library")
    window.show()
    profile = window.store.create_profile("Couleurs douces")
    window.reload_profiles(profile)

    def wait_job():
        limit = time.monotonic() + 180
        while window.busy() and time.monotonic() < limit:
            app.processEvents()
            time.sleep(.03)
        assert not window.busy(), "Worker did not finish"

    window.launch(reference_job(window.store, profile, paths[:6]))
    wait_job()
    assert len(window.store.references(profile)) == 6
    identifier = analysis_job(window.store, profile, paths)
    window.launch(identifier)
    wait_job()
    job = window.store.job(identifier)
    assert job["state"] == "done", job["error"]
    batch = job["payload"]["batch"]
    assert len(window.rows) == 12
    window.gallery.setCurrentIndex(window.model.index(3))
    limit = time.monotonic() + 20
    while window.pixmap is None and time.monotonic() < limit:
        app.processEvents()
        time.sleep(.03)
    assert window.pixmap is not None, "Preview process did not render"
    window.sliders["exposure"].setValue(15)
    window.decide("keep")
    window.store.validate(batch)
    window.rows = window.store.photos(batch)
    identifier = export_job(window.store, batch, directory / "exports")
    window.launch(identifier)
    wait_job()
    job = window.store.job(identifier)
    assert job["state"] == "done", job["error"]
    assert job["payload"]["outputs"]
    window.gallery.setCurrentIndex(window.model.index(3))
    limit = time.monotonic() + 15
    while window.pixmap is None and time.monotonic() < limit:
        app.processEvents()
        time.sleep(.03)
    app.processEvents()
    screenshot = ROOT / "test-output" / "atelier-desktop.png"
    window.grab().save(str(screenshot))
    window.close()
    print(f"Real-model desktop flow passed. Screenshot: {screenshot}")
    print(f"Outputs: {len(job['payload']['outputs'])}")


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    main()

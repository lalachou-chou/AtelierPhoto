"""XMP sidecar describing Atelier's global correction for RAW editors.

Lightroom / Camera Raw read the ``crs`` settings; darktable imports the
exposure, contrast and saturation values. Atelier's own values are kept in
their own namespace so that nothing is lost when a tool ignores ``crs``.
"""
from .imaging import IDENTITY_STYLE, effective


def sidecar(recipe, style, enabled=True, raw=True):
    total = effective(recipe, style) if enabled else dict(IDENTITY_STYLE)
    settings = {
        "crs:Exposure2012": f"{max(-5., min(5., total['exposure'])):+.2f}",
        "crs:Contrast2012": f"{round(max(-100, min(100, total['contrast'] * 200))):+d}",
        "crs:Saturation": f"{round(max(-100, min(100, total['saturation'] * 100))):+d}",
    }
    if raw:
        # Absolute Kelvin is unknown without the camera's as-shot white balance;
        # keep the shot's balance and record Atelier's warmth below.
        settings["crs:WhiteBalance"] = "As Shot"
    else:
        settings["crs:IncrementalTemperature"] = f"{round(max(-100, min(100, total['temperature'] * 40))):+d}"
    atelier = {f"atelier:{k}": f"{v:.4f}" for k, v in total.items()}
    atelier["atelier:FilterEnabled"] = "True" if enabled else "False"
    attributes = "\n".join(f'   {k}="{v}"' for k, v in {**settings, **atelier}.items())
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<x:xmpmeta xmlns:x="adobe:ns:meta/" x:xmptk="Atelier Photo">
 <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description rdf:about=""
   xmlns:crs="http://ns.adobe.com/camera-raw-settings/1.0/"
   xmlns:atelier="https://atelier-photo.local/ns/1.0/"
   crs:Version="15.0"
   crs:ProcessVersion="11.0"
   crs:HasSettings="True"
{attributes}/>
 </rdf:RDF>
</x:xmpmeta>
""".encode("utf-8")

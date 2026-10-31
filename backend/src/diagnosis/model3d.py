"""
3D model of the part a worker photographed.

Greywiz does not train a 3D model. It sends the photo to an open image-to-3D
model hosted on the Hugging Face hub (Tencent Hunyuan3D-2 by default) and
keeps the returned .glb mesh with the problem report. The photo leaves the
laptop for this step, so the UI only runs it when the worker asks.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

DEFAULT_SPACE = "tencent/Hunyuan3D-2"


def generate_model(photo_path: Path, out_path: Path) -> dict:
    """Create a .glb mesh from the photo; returns which hub model made it."""
    from gradio_client import Client, handle_file

    space = os.getenv("HF_3D_SPACE", DEFAULT_SPACE)
    token = os.getenv("HF_TOKEN") or None
    try:
        client = Client(space, token=token, verbose=False)
        result = client.predict(image=handle_file(str(photo_path)), api_name="/shape_generation")
    except Exception as e:
        raise RuntimeError(
            f"The 3D model service ({space} on Hugging Face) did not answer: {e}. "
            "Free public models have daily limits; add HF_TOKEN to backend/.env or try later."
        ) from e

    mesh = result[0]
    mesh_file = mesh.get("value") if isinstance(mesh, dict) else mesh
    if not mesh_file or not Path(mesh_file).exists():
        raise RuntimeError("The 3D model service returned no mesh.")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(mesh_file, out_path)
    return {"space": space, "size_bytes": out_path.stat().st_size}

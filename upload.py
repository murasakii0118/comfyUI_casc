"""Server route for uploading CASC files into ComfyUI input directory."""
from __future__ import annotations

import time
from pathlib import Path

try:
    from aiohttp import web  # type: ignore
    import folder_paths  # type: ignore
    from server import PromptServer  # type: ignore
except ImportError:
    web = None
    folder_paths = None
    PromptServer = None


_REGISTERED = False


def register_upload_route() -> None:
    global _REGISTERED
    if _REGISTERED or web is None or PromptServer is None or folder_paths is None:
        return
    _REGISTERED = True

    @PromptServer.instance.routes.post("/comfyui_casc/upload")
    async def upload_casc(request):
        reader = await request.multipart()
        field = await reader.next()
        if field is None or field.name != "file":
            return web.json_response({"error": "missing file field"}, status=400)
        original_name = Path(field.filename or "character.casc").name
        if Path(original_name).suffix.lower() != ".casc":
            return web.json_response({"error": "only .casc files are accepted"}, status=400)
        target_dir = Path(folder_paths.get_input_directory()) / "comfyUI_casc"
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / original_name
        if target.exists():
            target = target_dir / f"{target.stem}_{time.time_ns()}{target.suffix}"
        total = 0
        try:
            with target.open("wb") as output:
                while True:
                    chunk = await field.read_chunk(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > 2 * 1024 * 1024 * 1024:
                        target.unlink(missing_ok=True)
                        return web.json_response({"error": "file is larger than 2 GiB"}, status=413)
                    output.write(chunk)
        except Exception:
            target.unlink(missing_ok=True)
            raise
        return web.json_response({
            "filename": target.name,
            "value": f"comfyUI_casc/{target.name}",
            "size": total,
        })
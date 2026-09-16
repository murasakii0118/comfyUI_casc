"""ComfyUI nodes for Character Asset Studio CASC containers."""
from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path
from typing import Any

from .casc_format import (
    CascAsset,
    CascCharacter,
    CascError,
    CascIdentity,
    CascIntegrityError,
    load_casc,
)

try:
    import folder_paths  # type: ignore
except ImportError:
    folder_paths = None


CATEGORY = "CASC"
SETTING_SLOTS = (
    "Portrait", "Front", "Left", "Right", "Rear", "Top", "Bottom",
    "LeftFronthalf", "RightFronthalf", "LeftRearHalf", "RightRearHalf",
)


def _resolve_casc_path(value: Any) -> Path:
    if isinstance(value, dict):
        value = value.get("path") or value.get("filename") or value.get("name") or ""
    text = str(value or "").strip()
    candidate = Path(text).expanduser()
    if candidate.is_file():
        return candidate
    if folder_paths is not None:
        try:
            input_dir = Path(folder_paths.get_input_directory())
            for path in (input_dir / text, input_dir / Path(text).name):
                if path.is_file():
                    return path
        except Exception:
            pass
    return candidate


def _input_directory_files() -> list[str]:
    if folder_paths is None:
        return []
    try:
        directory = Path(folder_paths.get_input_directory())
        return sorted(path.name for path in directory.glob("*.casc"))
    except Exception:
        return []


def _temp_directory() -> Path:
    if folder_paths is not None:
        try:
            path = Path(folder_paths.get_temp_directory()) / "comfyUI_casc"
            path.mkdir(parents=True, exist_ok=True)
            return path
        except Exception:
            pass
    path = Path(tempfile.gettempdir()) / "comfyUI_casc"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _asset_temp_path(asset: CascAsset) -> Path:
    digest = asset.sha256_hex[:24]
    safe_name = Path(asset.file_name).name or "asset.bin"
    path = _temp_directory() / f"{digest}_{safe_name}"
    if not path.exists() or path.stat().st_size != len(asset.data):
        path.write_bytes(asset.data)
    return path


def _image_tensor(asset: CascAsset):
    try:
        import numpy as np  # type: ignore
        import torch  # type: ignore
        from PIL import Image  # type: ignore
    except ImportError as exc:
        raise RuntimeError("图片节点需要 ComfyUI 的 torch、numpy 和 Pillow 依赖") from exc
    from io import BytesIO
    try:
        image = Image.open(BytesIO(asset.data)).convert("RGB")
    except Exception as exc:
        raise RuntimeError(f"无法解码图片: {asset.file_name}") from exc
    array = np.asarray(image).astype(np.float32) / 255.0
    return torch.from_numpy(array)


def _empty_image_tensor():
    try:
        import torch  # type: ignore
    except ImportError as exc:
        raise RuntimeError("图片节点需要 ComfyUI 的 torch 依赖") from exc
    return torch.zeros((64, 64, 3), dtype=torch.float32)


def _image_batch(assets: list[CascAsset]):
    if not assets:
        raise RuntimeError("图片列表为空")
    import torch  # type: ignore
    images = [_image_tensor(asset) for asset in assets]
    height = max(image.shape[0] for image in images)
    width = max(image.shape[1] for image in images)
    normalized = []
    for image in images:
        if tuple(image.shape[:2]) != (height, width):
            image = torch.nn.functional.interpolate(image.permute(2, 0, 1).unsqueeze(0), size=(height, width), mode="bilinear", align_corners=False).squeeze(0).permute(1, 2, 0)
        normalized.append(image)
    return torch.stack(normalized, dim=0)


def _asset_ui_image(asset: CascAsset, prefix: str) -> dict[str, str]:
    try:
        from PIL import Image  # type: ignore
        from io import BytesIO
        image = Image.open(BytesIO(asset.data))
    except Exception as exc:
        raise RuntimeError(f"viewer 无法解码图片: {asset.file_name}") from exc
    name = f"{prefix}_{asset.sha256_hex[:16]}.png"
    output = _temp_directory() / name
    if not output.exists():
        image.convert("RGB").save(output, format="PNG")
    subfolder = "comfyUI_casc"
    return {"filename": name, "subfolder": subfolder, "type": "temp"}


def _friendly_error(exc: Exception) -> str:
    if isinstance(exc, CascIntegrityError):
        return f"CASC 完整性校验失败：{exc}"
    if isinstance(exc, CascError):
        return f"CASC 解码失败：{exc}"
    return str(exc)


def _select_assets(assets: list[CascAsset], asset_index: int, label: str) -> list[CascAsset]:
    if not assets:
        raise RuntimeError(f"{label}列表为空")
    if asset_index < 0:
        return assets
    if asset_index >= len(assets):
        raise RuntimeError(f"{label}索引越界：{asset_index}，可用范围为 -1 或 0-{len(assets) - 1}")
    return [assets[asset_index]]


class CascInput:
    @classmethod
    def INPUT_TYPES(cls):
        files = _input_directory_files()
        return {
            "required": {
                "casc_file": ("STRING", {"default": files[0] if files else "", "multiline": False, "dynamicPrompts": False}),
                "password": ("STRING", {"default": "", "multiline": False, "defaultVal": ""}),
            }
        }

    RETURN_TYPES = ("CASC_IDENTITIES",)
    RETURN_NAMES = ("identities",)
    FUNCTION = "load"
    CATEGORY = CATEGORY

    def load(self, casc_file: str, password: str):
        path = _resolve_casc_path(casc_file)
        try:
            character = load_casc(path, password)
        except Exception as exc:
            raise RuntimeError(_friendly_error(exc)) from exc
        return (character.identities,)

    @classmethod
    def IS_CHANGED(cls, casc_file: str, password: str):
        path = _resolve_casc_path(casc_file)
        try:
            stat = path.stat()
            return f"{path.resolve()}:{stat.st_mtime_ns}:{stat.st_size}:{hashlib.sha256(password.encode()).hexdigest()}"
        except OSError:
            return f"missing:{path}:{password}"


class CascIdentitySelector:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "identities": ("CASC_IDENTITIES",),
            "identity_index": ("INT", {"default": 0, "min": 0, "max": 9999, "step": 1}),
        }}

    RETURN_TYPES = ("CASC_IDENTITY",)
    RETURN_NAMES = ("identity",)
    FUNCTION = "select"
    CATEGORY = CATEGORY

    def select(self, identities: list[CascIdentity], identity_index: int):
        if not identities:
            raise RuntimeError("CASC 身份列表为空")
        if identity_index < 0 or identity_index >= len(identities):
            raise RuntimeError(f"身份索引越界：{identity_index}，可用范围 0-{len(identities) - 1}")
        return (identities[identity_index],)


class CascResourcesOutput:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"identity": ("CASC_IDENTITY",)}}

    RETURN_TYPES = ("CASC_IMAGE_LIST", "CASC_SETTING_IMAGE_LIST", "CASC_IMAGE_LIST", "CASC_AUDIO_LIST", "CASC_VIDEO_LIST", "CASC_LORA_LIST")
    RETURN_NAMES = ("generalImage", "settingImage", "DetailsImage", "refAudio", "refVideo", "privateLora")
    FUNCTION = "split"
    CATEGORY = CATEGORY

    def split(self, identity: CascIdentity):
        settings = [identity.setting_images[slot] for slot in SETTING_SLOTS if slot in identity.setting_images]
        return (identity.general_images, settings, identity.detail_images, identity.ref_audio, identity.ref_video, identity.private_lora)


class CascGetGeneralImage:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "generalImage": ("CASC_IMAGE_LIST",),
            "asset_index": ("INT", {"default": -1, "min": -1, "max": 9999, "step": 1}),
        }}

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("image",)
    FUNCTION = "get_images"
    CATEGORY = CATEGORY

    def get_images(self, generalImage: list[CascAsset], asset_index: int):
        return (_image_batch(_select_assets(generalImage, asset_index, "通用参考图")),)


class CascGetDetailsImage:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "DetailsImage": ("CASC_IMAGE_LIST",),
            "asset_index": ("INT", {"default": -1, "min": -1, "max": 9999, "step": 1}),
        }}

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("image",)
    FUNCTION = "get_images"
    CATEGORY = CATEGORY

    def get_images(self, DetailsImage: list[CascAsset], asset_index: int):
        return (_image_batch(_select_assets(DetailsImage, asset_index, "细节参考图")),)


class CascGetRefAudio:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "refAudio": ("CASC_AUDIO_LIST",),
            "asset_index": ("INT", {"default": -1, "min": -1, "max": 9999, "step": 1}),
        }}

    RETURN_TYPES = ("CASC_AUDIO",)
    RETURN_NAMES = ("audio",)
    FUNCTION = "get_audio"
    CATEGORY = CATEGORY

    def get_audio(self, refAudio: list[CascAsset], asset_index: int):
        assets = _select_assets(refAudio, asset_index, "音频")
        return ([str(_asset_temp_path(asset)) for asset in assets],)

class CascGetRefVideo:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"refVideo": ("CASC_VIDEO_LIST",)}}

    RETURN_TYPES = ("CASC_VIDEO",)
    RETURN_NAMES = ("video",)
    FUNCTION = "get_video"
    CATEGORY = CATEGORY

    def get_video(self, refVideo: list[CascAsset]):
        if not refVideo:
            raise RuntimeError("视频列表为空")
        return ([str(_asset_temp_path(asset)) for asset in refVideo],)


class CascGetPrivateLora:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "model": ("MODEL",),
            "clip": ("CLIP",),
            "privateLora": ("CASC_LORA_LIST",),
            "lora_index": ("INT", {"default": 0, "min": 0, "max": 9999, "step": 1}),
            "strength_model": ("FLOAT", {"default": 1.0, "min": -10.0, "max": 10.0, "step": 0.05}),
            "strength_clip": ("FLOAT", {"default": 1.0, "min": -10.0, "max": 10.0, "step": 0.05}),
        }}

    RETURN_TYPES = ("MODEL", "CLIP")
    RETURN_NAMES = ("model", "clip")
    FUNCTION = "get_lora"
    CATEGORY = CATEGORY

    def get_lora(self, model, clip, privateLora: list[CascAsset], lora_index: int, strength_model: float, strength_clip: float):
        if not privateLora:
            raise RuntimeError("Lora 列表为空")
        if lora_index < 0 or lora_index >= len(privateLora):
            raise RuntimeError(f"Lora 索引越界：{lora_index}")
        try:
            import comfy.sd  # type: ignore
            import comfy.utils  # type: ignore
        except ImportError as exc:
            raise RuntimeError("CASC Lora 节点需要在完整 ComfyUI 环境中运行") from exc
        lora_path = str(_asset_temp_path(privateLora[lora_index]))
        try:
            loaded = comfy.utils.load_torch_file(lora_path, safe_load=True, return_metadata=True)
        except TypeError:
            loaded = comfy.utils.load_torch_file(lora_path, safe_load=True)
        metadata = None
        if isinstance(loaded, tuple):
            lora = loaded[0]
            metadata = loaded[1] if len(loaded) > 1 else None
        else:
            lora = loaded
        try:
            return comfy.sd.load_lora_for_models(
                model,
                clip,
                lora,
                strength_model,
                strength_clip,
                lora_metadata=metadata,
            )
        except TypeError:
            return comfy.sd.load_lora_for_models(model, clip, lora, strength_model, strength_clip)


class CascGetSettingImage:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"settingImage": ("CASC_SETTING_IMAGE_LIST",)}}

    RETURN_TYPES = ("IMAGE",) * 11
    RETURN_NAMES = SETTING_SLOTS
    FUNCTION = "get_images"
    CATEGORY = CATEGORY

    def get_images(self, settingImage: list[CascAsset]):
        by_slot = {asset.slot: asset for asset in settingImage}
        return tuple((_image_tensor(by_slot[slot]) if slot in by_slot else _empty_image_tensor()).unsqueeze(0) for slot in SETTING_SLOTS)


class CascImageListViewer:
    OUTPUT_NODE = True

    @classmethod
    def INPUT_TYPES(cls):
        return {"optional": {
            "generalImage": ("CASC_IMAGE_LIST",),
            "settingImage": ("CASC_SETTING_IMAGE_LIST",),
            "DetailsImage": ("CASC_IMAGE_LIST",),
        }}

    RETURN_TYPES = ()
    FUNCTION = "view"
    CATEGORY = CATEGORY

    def view(self, generalImage=None, settingImage=None, DetailsImage=None):
        assets = []
        for title, group in (("general", generalImage), ("setting", settingImage), ("details", DetailsImage)):
            for asset in group or []:
                assets.append(_asset_ui_image(asset, title))
        return {"ui": {"images": assets}}


class CascIdentityViewer:
    OUTPUT_NODE = True

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"identities": ("CASC_IDENTITIES",)}}

    RETURN_TYPES = ()
    FUNCTION = "view"
    CATEGORY = CATEGORY

    def view(self, identities: list[CascIdentity]):
        lines = [f"{index}: {identity.name}" for index, identity in enumerate(identities)]
        return {"ui": {"text": lines}}


NODE_CLASS_MAPPINGS = {
    "casc_input": CascInput,
    "casc_identity_selector": CascIdentitySelector,
    "casc_resources_output": CascResourcesOutput,
    "casc_get_generalImage": CascGetGeneralImage,
    "casc_get_DetailsImage": CascGetDetailsImage,
    "casc_get_refAudio": CascGetRefAudio,
    "casc_get_refVideo": CascGetRefVideo,
    "casc_get_privateLora": CascGetPrivateLora,
    "casc_get_settingImage": CascGetSettingImage,
    "casc_imagelistviewer": CascImageListViewer,
    "casc_identityviewer": CascIdentityViewer,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "casc_input": "CASC 输入",
    "casc_identity_selector": "CASC 身份选择器",
    "casc_resources_output": "CASC 资源拆分",
    "casc_get_generalImage": "CASC 通用图片",
    "casc_get_DetailsImage": "CASC 细节图片",
    "casc_get_refAudio": "CASC 音频",
    "casc_get_refVideo": "CASC 视频",
    "casc_get_privateLora": "CASC Lora",
    "casc_get_settingImage": "CASC 标准机位图片",
    "casc_imagelistviewer": "CASC 图片集预览",
    "casc_identityviewer": "CASC 身份列表预览",
}
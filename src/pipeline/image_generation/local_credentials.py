from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class SiliconFlowSavedConfig:
    api_key: str = ""
    base_url: str = "https://api.siliconflow.cn/v1"
    generation_model: str = "Qwen/Qwen-Image"
    edit_model: str = "Qwen/Qwen-Image-Edit-2509"


class SiliconFlowCredentialStore:
    """Local, git-ignored settings for the direct SiliconFlow connection."""

    def __init__(self, root_dir: str | Path) -> None:
        self.path = Path(root_dir) / "data" / "model_gateway" / "siliconflow.json"

    def load(self) -> SiliconFlowSavedConfig:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return SiliconFlowSavedConfig()
        except Exception:
            return SiliconFlowSavedConfig()
        if not isinstance(payload, dict):
            return SiliconFlowSavedConfig()
        defaults = SiliconFlowSavedConfig()
        return SiliconFlowSavedConfig(
            api_key=str(payload.get("api_key") or "").strip(),
            base_url=str(payload.get("base_url") or defaults.base_url).strip(),
            generation_model=str(payload.get("generation_model") or defaults.generation_model).strip(),
            edit_model=str(payload.get("edit_model") or defaults.edit_model).strip(),
        )

    def save(self, config: SiliconFlowSavedConfig) -> Path:
        if not config.api_key.strip():
            raise ValueError("API Key 不能为空。")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(asdict(config), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass
        return self.path

    def clear(self) -> None:
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass


@dataclass(frozen=True)
class BananaProSavedConfig:
    api_key: str = ""
    base_url: str = "https://www.bananapro.site"
    generation_model: str = "nano-banana-pro"
    edit_model: str = "seedream-5-pro"
    resolution: str = "1K"
    aspect_ratio: str = "1:1"
    generation_mode: str = "standard"


class BananaProCredentialStore:
    """Local, git-ignored settings for the native BananaPro adapter."""

    def __init__(self, root_dir: str | Path) -> None:
        self.path = Path(root_dir) / "data" / "model_gateway" / "bananapro.json"

    def load(self) -> BananaProSavedConfig:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, ValueError):
            return BananaProSavedConfig()
        if not isinstance(payload, dict):
            return BananaProSavedConfig()
        defaults = BananaProSavedConfig()
        return BananaProSavedConfig(
            api_key=str(payload.get("api_key") or "").strip(),
            base_url=str(payload.get("base_url") or defaults.base_url).strip(),
            generation_model=str(
                payload.get("generation_model") or defaults.generation_model
            ).strip(),
            edit_model=str(payload.get("edit_model") or defaults.edit_model).strip(),
            resolution=str(payload.get("resolution") or defaults.resolution).strip(),
            aspect_ratio=str(payload.get("aspect_ratio") or defaults.aspect_ratio).strip(),
            generation_mode=str(
                payload.get("generation_mode") or defaults.generation_mode
            ).strip(),
        )

    def save(self, config: BananaProSavedConfig) -> Path:
        if not config.api_key.strip():
            raise ValueError("API Key 不能为空。")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(asdict(config), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass
        return self.path

    def clear(self) -> None:
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass


@dataclass(frozen=True)
class PublicImageHostSavedConfig:
    imgbb_api_key: str = ""
    expiration_s: int = 86400


class PublicImageHostCredentialStore:
    """Local credentials for turning local stage inputs into public URLs."""

    def __init__(self, root_dir: str | Path) -> None:
        self.path = Path(root_dir) / "data" / "model_gateway" / "public_image_host.json"

    def load(self) -> PublicImageHostSavedConfig:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, ValueError):
            return PublicImageHostSavedConfig()
        if not isinstance(payload, dict):
            return PublicImageHostSavedConfig()
        return PublicImageHostSavedConfig(
            imgbb_api_key=str(payload.get("imgbb_api_key") or "").strip(),
            expiration_s=int(payload.get("expiration_s") or 86400),
        )

    def save(self, config: PublicImageHostSavedConfig) -> Path:
        if not config.imgbb_api_key.strip():
            raise ValueError("ImgBB API Key 不能为空。")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(asdict(config), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass
        return self.path

    def clear(self) -> None:
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass

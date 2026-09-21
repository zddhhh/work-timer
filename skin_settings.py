"""各皮肤的可配置项，统一落在 config['skin_settings'] 下，便于后续扩展。"""
from __future__ import annotations

THUNDER_QUOTE_EXAMPLE = "我命由我不由天"
THUNDER_QUOTE_MAX = 12


def defaults() -> dict:
    return {"thunder": {"quote": ""}}


def normalize_quote(text: str | None) -> str:
    """去首尾空白、压成一行、限长；空串表示不显示点击字效。"""
    if not text:
        return ""
    line = str(text).replace("\r", "").replace("\n", "").strip()
    if not line:
        return ""
    return line[:THUNDER_QUOTE_MAX]


def merge(raw) -> dict:
    """与默认结构合并，丢弃未知键的类型错误。"""
    base = defaults()
    if not isinstance(raw, dict):
        return base
    th = raw.get("thunder")
    if isinstance(th, dict):
        base["thunder"]["quote"] = normalize_quote(th.get("quote"))
    return base


def read(cfg: dict) -> dict:
    return merge(cfg.get("skin_settings"))


def write(cfg: dict, skin_settings: dict) -> None:
    cfg["skin_settings"] = merge(skin_settings)


def thunder_quote(cfg: dict) -> str:
    return read(cfg)["thunder"]["quote"]


def set_thunder_quote(cfg: dict, text: str | None) -> str:
    ss = read(cfg)
    ss["thunder"]["quote"] = normalize_quote(text)
    write(cfg, ss)
    return ss["thunder"]["quote"]

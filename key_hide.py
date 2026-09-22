"""按键隐藏：单击指定键快速隐藏/显示计时窗。"""
from __future__ import annotations

# 默认 `（反引号），误触少；用户可在设置里改
DEFAULT_VK = 0xC0  # VK_OEM_3

_MODIFIER_VKS = frozenset(
    {
        0x10,
        0x11,
        0x12,
        0x5B,
        0x5C,
        0xA0,
        0xA1,
        0xA2,
        0xA3,
        0xA4,
        0xA5,
    }
)

_VK_LABELS: dict[int, str] = {
    0x08: "Backspace",
    0x09: "Tab",
    0x0D: "Enter",
    0x1B: "Esc",
    0x20: "空格",
    0x10: "Shift",
    0x11: "Ctrl",
    0x12: "Alt",
    0x5B: "Win",
    0x5C: "Win",
    0xC0: "`",
    0xBD: "-",
    0xBB: "=",
    0xDB: "[",
    0xDD: "]",
    0xDC: "\\",
    0xBA: ";",
    0xDE: "'",
    0xBC: ",",
    0xBE: ".",
    0xBF: "/",
    0x14: "Scroll Lock",
    0x91: "Scroll Lock",
    0x13: "Pause",
    0x2D: "Insert",
    0x2E: "Delete",
    0x24: "Home",
    0x23: "End",
    0x21: "Page Up",
    0x22: "Page Down",
    **{0x70 + i: f"F{i + 1}" for i in range(12)},
    **{0x41 + i: chr(ord("A") + i) for i in range(26)},
    **{0x30 + i: str(i) for i in range(10)},
}


def defaults() -> dict:
    return {"enabled": False, "vk": DEFAULT_VK}


def is_modifier(vk: int) -> bool:
    return int(vk) in _MODIFIER_VKS


def normalize_vk(vk) -> int | None:
    try:
        code = int(vk)
    except (TypeError, ValueError):
        return None
    if 0x08 <= code <= 0xFE:
        return code
    return None


def label(vk: int) -> str:
    code = normalize_vk(vk)
    if code is None:
        return "未设置"
    return _VK_LABELS.get(code, f"键 0x{code:02X}")


def merge(raw) -> dict:
    base = defaults()
    if not isinstance(raw, dict):
        return base
    base["enabled"] = bool(raw.get("enabled"))
    vk = normalize_vk(raw.get("vk"))
    if vk is not None:
        base["vk"] = vk
    return base


def migrate_legacy(cfg: dict, raw: dict) -> None:
    """ctrl_hide / esc_disguise → key_hide；曾开 Ctrl 隐藏的保留 Ctrl。"""
    if "key_hide" in raw and isinstance(raw.get("key_hide"), dict):
        cfg["key_hide"] = merge(raw["key_hide"])
        cfg.pop("ctrl_hide", None)
        return
    kh = merge(cfg.get("key_hide"))
    if "ctrl_hide" in raw:
        if bool(raw.get("ctrl_hide")):
            kh["enabled"] = True
            kh["vk"] = 0x11
        cfg["key_hide"] = kh
        cfg.pop("ctrl_hide", None)
        return
    if "esc_disguise" in raw:
        if bool(raw.get("esc_disguise")):
            kh["enabled"] = True
            kh["vk"] = 0x11
        cfg["key_hide"] = kh
        cfg.pop("esc_disguise", None)
        return
    cfg["key_hide"] = kh


def ensure_fields(cfg: dict) -> None:
    cfg["key_hide"] = merge(cfg.get("key_hide"))


def read(cfg: dict) -> dict:
    return merge(cfg.get("key_hide"))


def enabled(cfg: dict) -> bool:
    return bool(read(cfg).get("enabled"))


def vk(cfg: dict) -> int:
    return int(read(cfg).get("vk", DEFAULT_VK))


def set_enabled(cfg: dict, on: bool) -> bool:
    ensure_fields(cfg)
    cfg["key_hide"]["enabled"] = bool(on)
    return cfg["key_hide"]["enabled"]


def set_vk(cfg: dict, code: int) -> int:
    ensure_fields(cfg)
    vk_code = normalize_vk(code)
    if vk_code is None:
        raise ValueError("invalid vk")
    cfg["key_hide"]["vk"] = vk_code
    return vk_code


def menu_caption(cfg: dict) -> str:
    kh = read(cfg)
    if not kh["enabled"]:
        return "设置隐藏按键…"
    return f"设置隐藏按键…  （{label(kh['vk'])}）"

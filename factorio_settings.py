from __future__ import annotations

"""Factorio mod settings support.

This module implements the documented Factorio PropertyTree/mod-settings.dat
format and a conservative static scanner for the three settings-stage Lua files.
The binary codec is intentionally dependency-free and preserves unknown values.
"""

from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO
import json
import re
import shutil
import struct
import tempfile
import zipfile


SETTINGS_STAGE_FILES = (
    "settings.lua",
    "settings-updates.lua",
    "settings-final-fixes.lua",
)

PT_NONE = 0
PT_BOOL = 1
PT_NUMBER = 2
PT_STRING = 3
PT_LIST = 4
PT_DICTIONARY = 5
PT_SIGNED_INTEGER = 6
PT_UNSIGNED_INTEGER = 7


class SettingsCodecError(RuntimeError):
    pass


@dataclass
class PTNode:
    type_id: int
    value: Any = None
    any_type: bool = False


@dataclass
class ModSettingsDocument:
    version: tuple[int, int, int, int]
    quality_flag: bool
    root: PTNode


def _read_exact(stream: BinaryIO, size: int) -> bytes:
    data = stream.read(size)
    if len(data) != size:
        raise SettingsCodecError("Unexpected end of mod-settings.dat")
    return data


def _read_opt_string(stream: BinaryIO) -> str | None:
    is_none = struct.unpack("<B", _read_exact(stream, 1))[0]
    if is_none:
        return None
    length = struct.unpack("<B", _read_exact(stream, 1))[0]
    if length == 0xFF:
        length = struct.unpack("<I", _read_exact(stream, 4))[0]
    raw = _read_exact(stream, length)
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SettingsCodecError("Invalid UTF-8 string in mod-settings.dat") from exc


def _write_opt_string(stream: BinaryIO, value: str | None) -> None:
    if value is None:
        stream.write(struct.pack("<B", 1))
        return
    raw = value.encode("utf-8")
    stream.write(struct.pack("<B", 0))
    if len(raw) >= 0xFF:
        stream.write(struct.pack("<BI", 0xFF, len(raw)))
    else:
        stream.write(struct.pack("<B", len(raw)))
    stream.write(raw)


def _read_node(stream: BinaryIO) -> PTNode:
    type_id, any_type = struct.unpack("<BB", _read_exact(stream, 2))
    if type_id == PT_NONE:
        value = None
    elif type_id == PT_BOOL:
        value = bool(struct.unpack("<B", _read_exact(stream, 1))[0])
    elif type_id == PT_NUMBER:
        value = struct.unpack("<d", _read_exact(stream, 8))[0]
    elif type_id == PT_STRING:
        value = _read_opt_string(stream)
    elif type_id in (PT_LIST, PT_DICTIONARY):
        count = struct.unpack("<I", _read_exact(stream, 4))[0]
        if type_id == PT_DICTIONARY:
            value = OrderedDict()
            for _ in range(count):
                key = _read_opt_string(stream)
                if key is None:
                    raise SettingsCodecError("Dictionary entry has a null key")
                value[key] = _read_node(stream)
        else:
            value = []
            for _ in range(count):
                _ = _read_opt_string(stream)  # list entries use an empty/null-ish key slot
                value.append(_read_node(stream))
    elif type_id == PT_SIGNED_INTEGER:
        value = struct.unpack("<q", _read_exact(stream, 8))[0]
    elif type_id == PT_UNSIGNED_INTEGER:
        value = struct.unpack("<Q", _read_exact(stream, 8))[0]
    else:
        raise SettingsCodecError(f"Unknown PropertyTree type: {type_id}")
    return PTNode(type_id=type_id, value=value, any_type=bool(any_type))


def _write_node(stream: BinaryIO, node: PTNode) -> None:
    stream.write(struct.pack("<BB", int(node.type_id), int(bool(node.any_type))))
    if node.type_id == PT_NONE:
        return
    if node.type_id == PT_BOOL:
        stream.write(struct.pack("<B", int(bool(node.value))))
        return
    if node.type_id == PT_NUMBER:
        stream.write(struct.pack("<d", float(node.value)))
        return
    if node.type_id == PT_STRING:
        _write_opt_string(stream, None if node.value is None else str(node.value))
        return
    if node.type_id == PT_DICTIONARY:
        items = list((node.value or {}).items())
        stream.write(struct.pack("<I", len(items)))
        for key, child in items:
            _write_opt_string(stream, str(key))
            _write_node(stream, child)
        return
    if node.type_id == PT_LIST:
        values = list(node.value or [])
        stream.write(struct.pack("<I", len(values)))
        for child in values:
            _write_opt_string(stream, None)
            _write_node(stream, child)
        return
    if node.type_id == PT_SIGNED_INTEGER:
        stream.write(struct.pack("<q", int(node.value)))
        return
    if node.type_id == PT_UNSIGNED_INTEGER:
        stream.write(struct.pack("<Q", int(node.value)))
        return
    raise SettingsCodecError(f"Unknown PropertyTree type: {node.type_id}")


def read_mod_settings(path: Path) -> ModSettingsDocument:
    path = Path(path)
    try:
        with path.open("rb") as stream:
            version = struct.unpack("<HHHH", _read_exact(stream, 8))
            quality_flag = bool(struct.unpack("<B", _read_exact(stream, 1))[0])
            root = _read_node(stream)
            trailing = stream.read(1)
            if trailing:
                raise SettingsCodecError("Trailing bytes found in mod-settings.dat")
    except OSError as exc:
        raise SettingsCodecError(f"Cannot read {path}: {exc}") from exc
    if root.type_id != PT_DICTIONARY:
        raise SettingsCodecError("mod-settings.dat root is not a dictionary")
    return ModSettingsDocument(version=version, quality_flag=quality_flag, root=root)


def write_mod_settings(path: Path, document: ModSettingsDocument, *, backup: bool = True) -> Path | None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    backup_path = None
    if backup and path.exists():
        backup_path = path.with_name(path.name + ".bak")
        shutil.copy2(path, backup_path)

    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with open(fd, "wb", closefd=True) as stream:
            stream.write(struct.pack("<HHHH", *document.version))
            stream.write(struct.pack("<B", int(bool(document.quality_flag))))
            _write_node(stream, document.root)
            stream.flush()
        Path(temp_name).replace(path)
    except Exception:
        try:
            Path(temp_name).unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return backup_path


def node_to_python(node: PTNode) -> Any:
    if node.type_id == PT_DICTIONARY:
        return {key: node_to_python(value) for key, value in (node.value or {}).items()}
    if node.type_id == PT_LIST:
        return [node_to_python(value) for value in (node.value or [])]
    return node.value


def _python_to_node(value: Any, setting_type: str | None = None) -> PTNode:
    if setting_type == "int-setting":
        return PTNode(PT_SIGNED_INTEGER, int(value))
    if setting_type == "double-setting":
        return PTNode(PT_NUMBER, float(value))
    if setting_type == "bool-setting":
        return PTNode(PT_BOOL, bool(value))
    if setting_type == "string-setting":
        return PTNode(PT_STRING, str(value))
    if setting_type == "color-setting":
        if not isinstance(value, dict):
            raise SettingsCodecError("Color setting must be a dictionary")
        return PTNode(
            PT_DICTIONARY,
            OrderedDict((channel, PTNode(PT_NUMBER, float(value[channel]))) for channel in ("r", "g", "b", "a") if channel in value),
        )
    if value is None:
        return PTNode(PT_NONE, None)
    if isinstance(value, bool):
        return PTNode(PT_BOOL, value)
    if isinstance(value, int):
        return PTNode(PT_SIGNED_INTEGER, value)
    if isinstance(value, float):
        return PTNode(PT_NUMBER, value)
    if isinstance(value, str):
        return PTNode(PT_STRING, value)
    if isinstance(value, dict):
        return PTNode(PT_DICTIONARY, OrderedDict((str(k), _python_to_node(v)) for k, v in value.items()))
    if isinstance(value, list):
        return PTNode(PT_LIST, [_python_to_node(v) for v in value])
    raise SettingsCodecError(f"Unsupported setting value: {type(value).__name__}")


def settings_values(document: ModSettingsDocument) -> dict[str, dict[str, Any]]:
    output = {"startup": {}, "runtime-global": {}, "runtime-per-user": {}}
    root = document.root.value or {}
    for section in output:
        section_node = root.get(section)
        if not section_node or section_node.type_id != PT_DICTIONARY:
            continue
        for name, setting_node in (section_node.value or {}).items():
            if setting_node.type_id != PT_DICTIONARY:
                continue
            value_node = (setting_node.value or {}).get("value")
            if value_node is not None:
                output[section][name] = node_to_python(value_node)
    return output


def set_document_setting(document: ModSettingsDocument, section: str, name: str, value: Any, prototype_type: str | None = None) -> None:
    if section not in {"startup", "runtime-global", "runtime-per-user"}:
        raise SettingsCodecError(f"Unknown setting section: {section}")
    root = document.root.value
    if not isinstance(root, OrderedDict):
        root = OrderedDict(root or {})
        document.root.value = root
    section_node = root.get(section)
    if section_node is None:
        section_node = PTNode(PT_DICTIONARY, OrderedDict())
        root[section] = section_node
    if section_node.type_id != PT_DICTIONARY:
        raise SettingsCodecError(f"Section {section} is not a dictionary")
    settings_dict = section_node.value
    setting_node = settings_dict.get(name)
    if setting_node is None:
        setting_node = PTNode(PT_DICTIONARY, OrderedDict())
        settings_dict[name] = setting_node
    if setting_node.type_id != PT_DICTIONARY:
        raise SettingsCodecError(f"Setting {name} is not a dictionary")

    existing = setting_node.value.get("value")
    if existing is not None and prototype_type is None:
        new_node = _python_to_node(value)
        # Preserve the exact integer representation when practical.
        if existing.type_id in (PT_SIGNED_INTEGER, PT_UNSIGNED_INTEGER) and isinstance(value, int):
            new_node.type_id = existing.type_id
        elif existing.type_id == PT_NUMBER and isinstance(value, (int, float)) and not isinstance(value, bool):
            new_node.type_id = PT_NUMBER
        elif existing.type_id == PT_STRING:
            new_node.type_id = PT_STRING
        elif existing.type_id == PT_BOOL:
            new_node.type_id = PT_BOOL
    else:
        new_node = _python_to_node(value, prototype_type)
    setting_node.value["value"] = new_node


def infer_prototype_type(value: Any) -> str:
    if isinstance(value, bool):
        return "bool-setting"
    if isinstance(value, int):
        return "int-setting"
    if isinstance(value, float):
        return "double-setting"
    if isinstance(value, str):
        return "string-setting"
    if isinstance(value, dict) and {"r", "g", "b"}.issubset(value):
        return "color-setting"
    return "string-setting"


# ------------------------- Lua settings-stage scanner -------------------------

def read_settings_stage_sources(mod_path: Path, kind: str) -> dict[str, str]:
    mod_path = Path(mod_path)
    output: dict[str, str] = {}
    if kind == "folder":
        for filename in SETTINGS_STAGE_FILES:
            path = mod_path / filename
            if path.is_file():
                try:
                    output[filename] = path.read_text(encoding="utf-8-sig", errors="replace")
                except OSError:
                    pass
        return output

    if kind == "zip":
        try:
            with zipfile.ZipFile(mod_path, "r") as archive:
                for member in archive.namelist():
                    base = member.rsplit("/", 1)[-1]
                    if base not in SETTINGS_STAGE_FILES:
                        continue
                    try:
                        output[base] = archive.read(member).decode("utf-8-sig", errors="replace")
                    except (KeyError, OSError):
                        pass
        except (OSError, zipfile.BadZipFile):
            pass
    return output


def _mask_lua_comments(text: str) -> str:
    # Keep lengths/newlines stable so brace offsets remain valid.
    chars = list(text)
    i = 0
    n = len(chars)
    quote = None
    while i < n:
        ch = chars[i]
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in ('"', "'"):
            quote = ch
            i += 1
            continue
        if i + 1 < n and chars[i] == "-" and chars[i + 1] == "-":
            if i + 3 < n and chars[i + 2] == "[" and chars[i + 3] == "[":
                end = text.find("]]", i + 4)
                end = n - 2 if end < 0 else end
                for j in range(i, min(n, end + 2)):
                    if chars[j] != "\n":
                        chars[j] = " "
                i = end + 2
            else:
                end = text.find("\n", i + 2)
                end = n if end < 0 else end
                for j in range(i, end):
                    chars[j] = " "
                i = end
            continue
        i += 1
    return "".join(chars)


def _brace_pairs(text: str) -> dict[int, int]:
    pairs: dict[int, int] = {}
    stack: list[int] = []
    quote = None
    i = 0
    while i < len(text):
        ch = text[i]
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in ('"', "'"):
            quote = ch
        elif ch == "{":
            stack.append(i)
        elif ch == "}" and stack:
            start = stack.pop()
            pairs[start] = i
        i += 1
    return pairs


def _lua_scalar(raw: str) -> Any:
    raw = raw.strip().rstrip(",")
    if not raw:
        return None
    if raw in {"true", "false"}:
        return raw == "true"
    if raw == "nil":
        return None
    if (raw.startswith('"') and raw.endswith('"')) or (raw.startswith("'") and raw.endswith("'")):
        body = raw[1:-1]
        try:
            return bytes(body, "utf-8").decode("unicode_escape")
        except UnicodeDecodeError:
            return body
    if re.fullmatch(r"[-+]?\d+", raw):
        try:
            return int(raw)
        except ValueError:
            return None
    if re.fullmatch(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?", raw):
        try:
            return float(raw)
        except ValueError:
            return None
    return None


def _extract_simple_assignment(table_text: str, key: str) -> Any:
    pattern = re.compile(rf"(?:\b{re.escape(key)}\b|\[\s*[\"']{re.escape(key)}[\"']\s*\])\s*=\s*", re.I)
    match = pattern.search(table_text)
    if not match:
        return None
    i = match.end()
    if i >= len(table_text):
        return None
    if table_text[i] in ('"', "'"):
        quote = table_text[i]
        j = i + 1
        while j < len(table_text):
            if table_text[j] == "\\":
                j += 2
                continue
            if table_text[j] == quote:
                return _lua_scalar(table_text[i:j + 1])
            j += 1
        return None
    j = i
    while j < len(table_text) and table_text[j] not in ",\n}\r":
        j += 1
    return _lua_scalar(table_text[i:j])


def _extract_allowed_values(table_text: str) -> list[Any] | None:
    match = re.search(r"\ballowed_values\b\s*=\s*\{", table_text)
    if not match:
        return None
    start = table_text.find("{", match.start())
    depth = 0
    quote = None
    end = None
    i = start
    while i < len(table_text):
        ch = table_text[i]
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = None
        elif ch in ('"', "'"):
            quote = ch
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i
                break
        i += 1
    if end is None:
        return None
    body = table_text[start + 1:end]
    values: list[Any] = []
    token = ""
    quote = None
    for ch in body + ",":
        if quote:
            token += ch
            if ch == quote and not token.endswith("\\" + quote):
                quote = None
            continue
        if ch in ('"', "'"):
            quote = ch
            token += ch
        elif ch == ",":
            parsed = _lua_scalar(token)
            if parsed is not None:
                values.append(parsed)
            token = ""
        else:
            token += ch
    return values or None


def scan_setting_prototypes(sources: dict[str, str]) -> list[dict[str, Any]]:
    prototypes: OrderedDict[str, dict[str, Any]] = OrderedDict()
    type_re = re.compile(r"\btype\s*=\s*[\"'](bool-setting|int-setting|double-setting|string-setting|color-setting)[\"']", re.I)
    for filename in SETTINGS_STAGE_FILES:
        original = sources.get(filename)
        if not original:
            continue
        text = _mask_lua_comments(original)
        pairs = _brace_pairs(text)
        for match in type_re.finditer(text):
            candidates = [(start, end) for start, end in pairs.items() if start < match.start() < end]
            if not candidates:
                continue
            start, end = max(candidates, key=lambda item: item[0])
            table = text[start:end + 1]
            name = _extract_simple_assignment(table, "name")
            setting_type = _extract_simple_assignment(table, "setting_type")
            if not isinstance(name, str) or setting_type not in {"startup", "runtime-global", "runtime-per-user"}:
                continue
            prototype = {
                "name": name,
                "type": match.group(1).lower(),
                "setting_type": setting_type,
                "default_value": _extract_simple_assignment(table, "default_value"),
                "minimum_value": _extract_simple_assignment(table, "minimum_value"),
                "maximum_value": _extract_simple_assignment(table, "maximum_value"),
                "allowed_values": _extract_allowed_values(table),
                "hidden": bool(_extract_simple_assignment(table, "hidden") or False),
                "order": _extract_simple_assignment(table, "order"),
                "source": filename,
                "detected_from_dat": False,
            }
            prototypes[name] = prototype
    return list(prototypes.values())


def normalize_mod_prefixes(mod_name: str, title: str = "") -> list[str]:
    candidates = []
    for value in (mod_name, re.sub(r"(?:[-_.]?\d+)+$", "", mod_name), title):
        value = re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")
        if len(value) >= 4 and value not in candidates:
            candidates.append(value)
        compact = value.replace("-", "")
        if len(compact) >= 5 and compact not in candidates:
            candidates.append(compact)
    return candidates


def setting_name_likely_belongs_to_mod(setting_name: str, mod_name: str, title: str = "") -> bool:
    normalized = re.sub(r"[^a-z0-9]+", "-", setting_name.lower()).strip("-")
    compact = normalized.replace("-", "")
    for prefix in normalize_mod_prefixes(mod_name, title):
        if "-" in prefix:
            if normalized == prefix or normalized.startswith(prefix + "-"):
                return True
        elif compact == prefix or compact.startswith(prefix):
            return True
    return False


def parse_color_input(value: Any) -> dict[str, float]:
    if isinstance(value, dict):
        result = {key: float(value.get(key, 1.0 if key == "a" else 0.0)) for key in ("r", "g", "b", "a")}
    elif isinstance(value, str):
        raw = value.strip()
        if raw.startswith("{"):
            parsed = json.loads(raw)
            return parse_color_input(parsed)
        parts = [part.strip() for part in raw.split(",") if part.strip()]
        if len(parts) not in {3, 4}:
            raise ValueError("Color must be r,g,b or r,g,b,a")
        nums = [float(part) for part in parts]
        if len(nums) == 3:
            nums.append(1.0)
        result = dict(zip(("r", "g", "b", "a"), nums))
    else:
        raise ValueError("Invalid color value")
    for key, number in result.items():
        if number < 0 or number > 1:
            raise ValueError(f"Color channel {key} must be between 0 and 1")
    return result


def coerce_setting_value(prototype: dict[str, Any], value: Any) -> Any:
    kind = prototype.get("type")
    if kind == "bool-setting":
        if isinstance(value, bool):
            result = value
        elif str(value).strip().lower() in {"true", "1", "yes", "on"}:
            result = True
        elif str(value).strip().lower() in {"false", "0", "no", "off"}:
            result = False
        else:
            raise ValueError("Boolean value must be true or false")
    elif kind == "int-setting":
        result = int(value)
    elif kind == "double-setting":
        result = float(value)
    elif kind == "string-setting":
        result = str(value)
    elif kind == "color-setting":
        result = parse_color_input(value)
    else:
        result = value

    minimum = prototype.get("minimum_value")
    maximum = prototype.get("maximum_value")
    if kind in {"int-setting", "double-setting"}:
        if minimum is not None and result < minimum:
            raise ValueError(f"Value must be >= {minimum}")
        if maximum is not None and result > maximum:
            raise ValueError(f"Value must be <= {maximum}")
    allowed = prototype.get("allowed_values")
    if allowed is not None and result not in allowed:
        raise ValueError(f"Value must be one of: {', '.join(map(str, allowed))}")
    return result

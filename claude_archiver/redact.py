"""Редакция экспортов claude.ai.

Делает две вещи рекурсивно по любому JSON:
  - заменяет все UUID на стабильные плейсхолдеры uuid_1, uuid_2, ...
    (одинаковый UUID всегда получает один и тот же плейсхолдер);
  - полностью удаляет чувствительные поля (по умолчанию email и телефон).
"""
import re

UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)

# Ключи, которые вырезаем из любого объекта целиком.
DEFAULT_DROP_KEYS = frozenset({"email_address", "verified_phone_number"})


class Redactor:
    """Хранит карту UUID->плейсхолдер, чтобы ссылки оставались согласованными
    в пределах одного прогона (даже между несколькими файлами)."""

    def __init__(self, drop_keys=DEFAULT_DROP_KEYS):
        self.drop_keys = frozenset(drop_keys)
        self.mapping = {}
        self._counter = 0

    def _placeholder(self, uuid: str) -> str:
        if uuid not in self.mapping:
            self._counter += 1
            self.mapping[uuid] = f"uuid_{self._counter}"
        return self.mapping[uuid]

    def redact(self, obj):
        if isinstance(obj, dict):
            return {
                k: self.redact(v)
                for k, v in obj.items()
                if k not in self.drop_keys
            }
        if isinstance(obj, list):
            return [self.redact(v) for v in obj]
        if isinstance(obj, str) and UUID_RE.match(obj):
            return self._placeholder(obj)
        return obj


def safe_filename(name: str) -> str:
    return "".join(c if c.isalnum() or c in ("-", "_", ".") else "_" for c in name)

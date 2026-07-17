"""Entity resolver -- lightweight NER with regex + CJK analysis."""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Entity:
    name: str
    type: str
    aliases: list[str] = field(default_factory=list)
    confidence: float = 1.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return dict(name=self.name, type=self.type)

    @classmethod
    def from_dict(cls, d: dict) -> "Entity":
        return cls(name=d["name"], type=d.get("type", "CONCEPT"))


class EntityResolver:
    PROJ_RE = re.compile(r"(?:项目|工程|方案|系统)[<“]?([一-鿿A-Za-z0-9_-]{2,40})[>”]?")
    TECH_RE = re.compile(r"(?:使用|用|基于|利用|采用)(?:\s*)([A-Z][a-zA-Z0-9+./_-]{2,40})")
    ACRONYM_RE = re.compile(r"(?:^|[^a-zA-Z])([A-Z]{2,8})(?=[^a-zA-Z]|$)")
    CJK_RE = re.compile(r"[一-鿿]{2,}")
    CONCEPT_KW = ["架构","系统","方案","引擎","平台","模块","框架","协议"]

    def extract(self, text: str) -> list[Entity]:
        if not text or not text.strip():
            return []
        seen: dict[str, Entity] = {}
        for m in self.PROJ_RE.finditer(text):
            name = m.group(1).strip()
            if name and name not in seen:
                seen[name] = Entity(name=name, type="PROJECT")
        for m in self.TECH_RE.finditer(text):
            name = m.group(1).strip()
            if name and name not in seen:
                seen[name] = Entity(name=name, type="TECH")
        for m in self.ACRONYM_RE.finditer(text):
            name = m.group(1)
            if name not in seen and len(name) >= 2:
                seen[name] = Entity(name=name, type="TECH")
        for m in self.CJK_RE.finditer(text):
            token = m.group(0)
            if token not in seen and any(kw in token for kw in self.CONCEPT_KW):
                seen[token] = Entity(name=token, type="CONCEPT")
        return list(seen.values())

    def extract_ids(self, text: str) -> list[str]:
        return [e.name for e in self.extract(text)]
"""Phase 1: Wire CognitivePipeline into hooks."""
import os, json, re

def patch_file(fpath, old, new, count=1):
    with open(fpath, encoding="utf-8") as f:
        content = f.read()
    if old not in content:
        print(f"  SKIP: pattern not found in {os.path.basename(fpath)}")
        return False
    content = content.replace(old, new, count)
    with open(fpath, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"  PATCHED: {os.path.basename(fpath)}")
    return True

BASE = "E:/codex/cdx-brain"
os.chdir(BASE)

# === 1. pipeline.py: add save_state/load_state + session_count ===
content = open("cdx_brain/memos/pipeline.py", encoding="utf-8").read()

if "self._session_count" not in content:
    content = content.replace(
        "self._current_traces: list[TraceRow] = []",
        "self._current_traces: list[TraceRow] = []\n        self._session_count = 0  # incremented on process_session_end"
    )

content = content.replace(
    'results: dict[str, Any] = {\n            "stage": {}',
    'self._session_count += 1\n\n        results: dict[str, Any] = {\n            "stage": {}',
    1
)

if "def save_state" not in content:
    save_code = '''

    # -- State Persistence ----------------------------------

    def save_state(self, config_dir: str = "") -> None:
        """Persist pipeline state (policies, skills, world model) to JSON."""
        import json
        from pathlib import Path
        base = Path(config_dir) if config_dir else Path.home() / ".cdx-brain" / "data"
        base.mkdir(parents=True, exist_ok=True)
        path = base / "pipeline_state.json"
        state = {
            "version": 1,
            "session_count": getattr(self, "_session_count", 0),
            "policies": [p.to_dict() for p in self._policies],
            "skills": [s.to_dict() for s in self._skills],
            "world_model": self.world_model.to_dict(),
        }
        path.write_text(json.dumps(state, ensure_ascii=False, default=str), encoding="utf-8")

    @classmethod
    def load_state(
        cls,
        config_dir: str = "",
        config: Optional[CognitivePipelineConfig] = None,
    ) -> "CognitivePipeline":
        """Load pipeline state from JSON, returning a fresh pipeline."""
        import json
        from pathlib import Path
        pipeline = cls(config)
        base = Path(config_dir) if config_dir else Path.home() / ".cdx-brain" / "data"
        path = base / "pipeline_state.json"
        if not path.is_file():
            return pipeline
        try:
            state = json.loads(path.read_text("utf-8"))
            pipeline._session_count = state.get("session_count", 0)
            pipeline._policies = [PolicyRow.from_dict(p) for p in state.get("policies", [])]
            pipeline._skills = [SkillRow.from_dict(s) for s in state.get("skills", [])]
            wm_data = state.get("world_model", {})
            if wm_data:
                pipeline.world_model = WorldModel.from_dict(wm_data, pipeline._config.world_model)
        except (OSError, json.JSONDecodeError, KeyError):
            pass
        return pipeline

'''
    if 'if __name__ == "__main__":' in content:
        content = content.replace('if __name__ == "__main__":', save_code + '\nif __name__ == "__main__":')
    else:
        content = content.rstrip() + "\n" + save_code
    
    open("cdx_brain/memos/pipeline.py", "w", encoding="utf-8").write(content)
    print("  pipeline.py: +save_state/load_state + session_count")

# === 2. config.py: enable L3+Skill by default ===
patch_file("cdx_brain/config.py",
    "PipelineStage.L2_INDUCTION,\n        }",
    "PipelineStage.L2_INDUCTION,\n            PipelineStage.L3_WORLD_MODEL,\n            PipelineStage.SKILL_CRYSTALLIZATION,\n        }"
)

# === 3. inject.py: add cognitive artifact search ===
inject_content = open("cdx_brain/inject.py", encoding="utf-8").read()
if "cognitive" not in inject_content:
    cognitive_search = '''

# -- Source: Cognitive pipeline artifacts --


def search_cognitive(query: str, limit: int = 3) -> list[dict]:
    """Search pipeline state for matching policies and concepts."""
    import json
    from pathlib import Path
    state_path = Path(CACHE_PATH).parent / "pipeline_state.json"
    if not state_path.is_file():
        return []
    try:
        state = json.loads(state_path.read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    query_tokens = set(re.findall(r"[a-z0-9_\\u4e00-\\u9fff\\-]{2,}", query.lower()))
    if not query_tokens:
        return []
    results = []
    for p in state.get("policies", []):
        name = p.get("name", "")
        desc = p.get("description", "")
        trigger = p.get("trigger_pattern", "")
        combined = (name + " " + desc + " " + trigger).lower()
        q_hits = sum(1 for tok in query_tokens if tok in combined)
        if q_hits > 0:
            results.append({
                "id": "policy:" + p.get("id", name),
                "session_id": name,
                "user_content": "[Policy] " + name + "\\n" + desc[:200],
                "assistant_content": "",
                "reward": q_hits / max(len(query_tokens), 1),
                "tags": ["cognitive", "policy"],
                "created_at": p.get("created_at", ""),
                "source": "cognitive",
                "score": q_hits / max(len(query_tokens), 1),
            })
    wm = state.get("world_model", {})
    for cid, cdata in wm.get("concepts", {}).items():
        label = cdata.get("label", "")
        desc = cdata.get("description", "")
        combined = (label + " " + desc).lower()
        q_hits = sum(1 for tok in query_tokens if tok in combined)
        if q_hits > 0:
            results.append({
                "id": "concept:" + cid,
                "session_id": label,
                "user_content": "[Concept] " + label + "\\n" + desc[:200],
                "assistant_content": "",
                "reward": q_hits / max(len(query_tokens), 1),
                "tags": ["cognitive", "concept"],
                "created_at": cdata.get("created_at", ""),
                "source": "cognitive",
                "score": q_hits / max(len(query_tokens), 1),
            })
    results.sort(key=lambda r: r["score"], reverse=True)
    return results[:limit]

'''

    inject_content = inject_content.replace("def search_ov", cognitive_search + "\ndef search_ov", 1)
    inject_content = inject_content.replace(
        "ov_results = search_ov(prompt, limit=8)",
        "ov_results = search_ov(prompt, limit=8)\n    cognitive_results = search_cognitive(prompt, limit=3)"
    )
    inject_content = inject_content.replace(
        "merged = rrf_merge([local_results, native_results, codex_results, ov_results], k=60)",
        "merged = rrf_merge([local_results, native_results, codex_results, ov_results, cognitive_results], k=60)"
    )
    # Update system message
    inject_content = inject_content.replace(
        "f"{total} memories injected (FTS5:{local_n}",
        "f"{total} memories injected (FTS5:{local_n}"
    )
    open("cdx_brain/inject.py", "w", encoding="utf-8").write(inject_content)
    print("  inject.py: +cognitive artifact search")

print("\\nPhase 1 complete!")

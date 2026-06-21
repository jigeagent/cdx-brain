"""Cognitive pipeline orchestration — chains L1 → L2 → L3 → Skill
into a configurable processing pipeline with event hooks.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

from cdx_brain.memos.policy import PolicyConfig, PolicyInducer, PolicyRow
from cdx_brain.memos.reward import OutcomeSignal, RewardConfig, RewardEngine
from cdx_brain.memos.skill import SkillCrystallizer, SkillCrystallizerConfig, SkillRow
from cdx_brain.memos.memo_types import TraceRow
from cdx_brain.memos.world_model import WorldModel, WorldModelConfig

logger = logging.getLogger(__name__)


class PipelineStage(Enum):
    """Stages in the cognitive pipeline."""

    L1_CAPTURE = "l1_capture"
    REWARD = "reward"
    L2_INDUCTION = "l2_induction"
    L3_WORLD_MODEL = "l3_world_model"
    SKILL_CRYSTALLIZATION = "skill_crystallization"


# Type for pipeline event hooks
StageHook = Callable[[PipelineStage, dict[str, Any]], None]


@dataclass
class CognitivePipelineConfig:
    """Top-level configuration for the cognitive pipeline."""

    enabled_stages: set[PipelineStage] = field(
        default_factory=lambda: {
            PipelineStage.L1_CAPTURE,
            PipelineStage.REWARD,
            PipelineStage.L2_INDUCTION,
            PipelineStage.L3_WORLD_MODEL,
            PipelineStage.SKILL_CRYSTALLIZATION,
        }
    )
    """Which stages are active. L3 and Skill are opt-in by default."""

    auto_reward_on_session_end: bool = True
    """Automatically apply session-level reward when session ends."""

    reward: RewardConfig = field(default_factory=RewardConfig)
    policy: PolicyConfig = field(default_factory=PolicyConfig)
    world_model: WorldModelConfig = field(default_factory=WorldModelConfig)
    skill: SkillCrystallizerConfig = field(default_factory=SkillCrystallizerConfig)


class CognitivePipeline:
    """Orchestrates the full MemOS cognitive pipeline.

    L1 Capture → Reward → L2 Induction → L3 World Model → Skill Crystallization
    """

    def __init__(
        self,
        config: Optional[CognitivePipelineConfig] = None,
    ):
        self._config = config or CognitivePipelineConfig()
        self._hooks: list[StageHook] = []

        # Initialize engines
        self.reward_engine = RewardEngine(self._config.reward)
        self.policy_inducer = PolicyInducer(self._config.policy)
        self.world_model = WorldModel(self._config.world_model)
        self.skill_crystallizer = SkillCrystallizer(self._config.skill)

        # State
        self._policies: list[PolicyRow] = []
        self._skills: list[SkillRow] = []
        self._current_traces: list[TraceRow] = []
        self._session_count = 0

    # ── Hooks ─────────────────────────────────────────────

    def add_hook(self, hook: StageHook) -> None:
        """Register a pipeline stage event hook."""
        self._hooks.append(hook)

    def _emit(self, stage: PipelineStage, context: dict[str, Any]) -> None:
        """Emit a stage event to all registered hooks."""
        for hook in self._hooks:
            try:
                hook(stage, context)
            except Exception as e:
                logger.warning("Pipeline hook failed at %s: %s", stage.value, e)

    # ── Pipeline Execution ────────────────────────────────

    def process_trace(
        self,
        trace: TraceRow,
    ) -> TraceRow:
        """Process a single trace through the enabled pipeline stages.

        Args:
            trace: The captured L1 trace to process.

        Returns:
            The processed trace (may be enriched with reward, etc.).
        """
        self._current_traces.append(trace)

        # L1 is already captured by the provider — this stage validates
        self._emit(PipelineStage.L1_CAPTURE, {"trace": trace})

        return trace

    def process_session_end(
        self,
        traces: list[TraceRow],
        session_success: bool = True,
    ) -> dict[str, Any]:
        """Process all traces at session end through the full pipeline.

        Args:
            traces: All traces from the session.
            session_success: Whether the session was successful.

        Returns:
            Results from each active pipeline stage.
        """
        self._session_count += 1

        results: dict[str, Any] = {
            "stage": {},
            "new_policies": [],
            "new_concepts": [],
            "new_skills": [],
            "updated_traces": traces,
        }

        # ── Reward Stage ──────────────────────────────────
        if PipelineStage.REWARD in self._config.enabled_stages:
            if self._config.auto_reward_on_session_end:
                updated = self.reward_engine.compute_session_reward(
                    traces, session_success=session_success,
                )
                results["updated_traces"] = updated
                results["stage"]["reward"] = {
                    "applied": True,
                    "stats": self.reward_engine.aggregate_rewards(updated),
                }
                self._emit(PipelineStage.REWARD, results)
            else:
                results["stage"]["reward"] = {"applied": False}

        # ── L2 Induction Stage ────────────────────────────
        if PipelineStage.L2_INDUCTION in self._config.enabled_stages:
            new_policies = self.policy_inducer.batch_induce(
                traces=results["updated_traces"],
                existing_policies=self._policies,
            )
            if len(new_policies) > len(self._policies):
                induced = new_policies[len(self._policies):]
                results["new_policies"] = induced
                self._policies = new_policies
                results["stage"]["induction"] = {
                    "new_count": len(induced),
                    "total": len(self._policies),
                }
            else:
                results["stage"]["induction"] = {"new_count": 0, "total": len(self._policies)}
            self._emit(PipelineStage.L2_INDUCTION, results)

        # ── L3 World Model Stage ──────────────────────────
        if PipelineStage.L3_WORLD_MODEL in self._config.enabled_stages:
            new_concepts = self.world_model.cluster(
                traces=results["updated_traces"],
                policies=self._policies,
            )
            results["new_concepts"] = new_concepts

            # Extract triples from new traces
            triple_count = 0
            for t in results["updated_traces"]:
                triples = self.world_model.extract_triples(t)
                triple_count += len(triples)

            results["stage"]["world_model"] = {
                "new_concepts": len(new_concepts),
                "total_concepts": len(self.world_model.list_concepts()),
                "triples_extracted": triple_count,
                "total_triples": len(self.world_model.list_triples()),
            }
            self._emit(PipelineStage.L3_WORLD_MODEL, results)

        # ── Skill Crystallization Stage ───────────────────
        if PipelineStage.SKILL_CRYSTALLIZATION in self._config.enabled_stages:
            new_skills = self.skill_crystallizer.batch_crystallize(
                policies=self._policies,
                existing_skills=self._skills,
            )
            results["new_skills"] = new_skills
            self._skills.extend(new_skills)
            results["stage"]["skill"] = {
                "new_skills": len(new_skills),
                "total_skills": len(self._skills),
            }
            self._emit(PipelineStage.SKILL_CRYSTALLIZATION, results)

        return results

    def process_outcome(
        self,
        traces: list[TraceRow],
        signal: OutcomeSignal,
        target_turn_index: Optional[int] = None,
        manual_value: float = 0.0,
    ) -> list[TraceRow]:
        """Apply an outcome signal and re-run downstream stages.

        Args:
            traces: Trace sequence.
            signal: Outcome signal type.
            target_turn_index: Which turn triggered the signal.
            manual_value: Custom reward for MANUAL_REWARD.

        Returns:
            Updated traces with rewards applied.
        """
        # Apply reward
        updated = self.reward_engine.apply_outcome(
            traces, signal, target_turn_index, manual_value,
        )

        # Re-run induction if reward stage changed rewards
        if PipelineStage.L2_INDUCTION in self._config.enabled_stages:
            old_count = len(self._policies)
            self._policies = self.policy_inducer.batch_induce(
                traces=updated,
                existing_policies=self._policies,
            )
            if len(self._policies) > old_count:
                logger.info("Induced %d new policies from outcome signal", len(self._policies) - old_count)

        return updated

    # ── State Access ──────────────────────────────────────

    @property
    def policies(self) -> list[PolicyRow]:
        return list(self._policies)

    @property
    def skills(self) -> list[SkillRow]:
        return list(self._skills)

    @property
    def concepts(self) -> list[Any]:
        return self.world_model.list_concepts()

    @property
    def triples(self) -> list[Any]:
        return self.world_model.list_triples()

    def get_stats(self) -> dict[str, Any]:
        """Get pipeline statistics."""
        return {
            "traces_processed": len(self._current_traces),
            "policies": len(self._policies),
            "skills": len(self._skills),
            "concepts": len(self.world_model.list_concepts()),
            "triples": len(self.world_model.list_triples()),
            "enabled_stages": [s.value for s in self._config.enabled_stages],
        }

    def reset(self) -> None:
        """Reset pipeline state (for testing)."""
        self._policies = []
        self._skills = []
        self._current_traces = []
        self.world_model = WorldModel(self._config.world_model)
        self.reward_engine = RewardEngine(self._config.reward)
        self.policy_inducer = PolicyInducer(self._config.policy)
        self.skill_crystallizer = SkillCrystallizer(self._config.skill)


            # Sync cognitive state to OV (best-effort, no config needed)
        try:
            import os
            ov_url = os.environ.get("CDX_BRAIN_OV_URL", "")
            if ov_url:
                from cdx_brain.federation.sync import sync_pipeline_to_ov
                sync_state = {
                    "policies": [p.to_dict() for p in self._policies],
                    "skills": [s.to_dict() for s in self._skills],
                    "world_model": self.world_model.to_dict(),
                }
                counts = sync_pipeline_to_ov(sync_state, ov_url)
                if any(counts.values()):
                    logger.info("synced to OV: %s", counts)
        except Exception:
            pass

        # -- Relation Extraction --
        try:
            conn = self._get_db_connection()
            if conn is not None:
                from cdx_brain.retrieval.extractor import RelationExtractor
                policies_dict = [p.to_dict() for p in self._policies]
                concepts_dict = [c.to_dict() for c in self.world_model.list_concepts()]
                extractor = RelationExtractor(conn)
                new_relations = extractor.extract(policies=policies_dict, concepts=concepts_dict)
                results["new_relations"] = new_relations
                results["stage"]["relation_extraction"] = {"count": len(new_relations)}
                conn.close()
        except Exception:
            logger.warning("RelationExtraction failed", exc_info=True)

# -- State Persistence ----------------------------------

    

    def sync_to_ov(self, ov_url: str = "", agent: str = "comsam") -> dict:
        """Sync pipeline cognitive state to OV (best-effort)."""
        if not ov_url:
            return {}
        try:
            from cdx_brain.federation.sync import sync_pipeline_to_ov
            state = {
                "policies": [p.to_dict() for p in self._policies],
                "skills": [s.to_dict() for s in self._skills],
                "world_model": self.world_model.to_dict(),
            }
            return sync_pipeline_to_ov(state, ov_url, agent)
        except Exception:
            import logging
            logging.getLogger(__name__).warning("sync_to_ov failed", exc_info=True)
            return {}


    def _get_db_connection(self):
        """Get an SQLite connection to cache.db (best-effort)."""
        try:
            from pathlib import Path
            import sqlite3
            cache_path = Path.home() / ".cdx-brain" / "data" / "cache.db"
            if cache_path.is_file():
                return sqlite3.connect(str(cache_path))
        except Exception:
            pass
        return None

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

        # ── Baidu Netdisk sync (best-effort) ─────
        try:
            from cdx_brain.sync.bdpan import sync_pipeline_state
            sync_pipeline_state()
        except Exception:
            pass


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
            logger.info("pipeline state loaded: %d policies, %d skills, %d sessions",
                        len(pipeline._policies), len(pipeline._skills), pipeline._session_count)
        except (OSError, json.JSONDecodeError, KeyError) as exc:
            logger.warning("pipeline state load failed: %s", exc)
        return pipeline


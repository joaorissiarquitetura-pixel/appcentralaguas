from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any


class GotinhaEmotion(StrEnum):
    ALEGRIA = "ALEGRIA"
    TRISTEZA = "TRISTEZA"
    SEDE = "SEDE"
    RAIVA = "RAIVA"
    CHATEADA = "CHATEADA"
    CONFUSAO = "CONFUSAO"
    SUSTO = "SUSTO"
    CURIOSIDADE = "CURIOSIDADE"
    DETERMINACAO = "DETERMINACAO"


OFFICIAL_EMOTIONS = tuple(GotinhaEmotion)
DEFAULT_TRANSITIONS = (
    "ALEGRIA>TRISTEZA",
    "TRISTEZA>SEDE",
    "SEDE>ALEGRIA",
    "CONFUSAO>CURIOSIDADE",
    "CHATEADA>RAIVA",
    "CURIOSIDADE>DETERMINACAO",
)


@dataclass(frozen=True)
class GotinhaManifest:
    version: int
    emotions: dict[str, str]
    transitions: dict[str, list[str]]


class GotinhaAssetRegistry:
    def __init__(
        self,
        manifest_path: str | Path = "app/static/assets/gotinha/manifest.json",
        static_prefix: str = "/static/assets/gotinha/",
        fallback_asset: str = "/static/img/mascote_novo.png",
    ):
        self.manifest_path = Path(manifest_path)
        self.static_prefix = static_prefix.rstrip("/") + "/"
        self.fallback_asset = fallback_asset
        self.manifest = self._load_manifest()

    def _load_manifest(self) -> GotinhaManifest:
        if not self.manifest_path.exists():
            return GotinhaManifest(
                version=1,
                emotions={emotion.value: "" for emotion in OFFICIAL_EMOTIONS},
                transitions={transition: [] for transition in DEFAULT_TRANSITIONS},
            )

        with self.manifest_path.open("r", encoding="utf-8") as source:
            data = json.load(source)

        emotions = data.get("emotions")
        transitions = data.get("transitions")
        if not isinstance(emotions, dict) or not isinstance(transitions, dict):
            raise ValueError("Manifesto da Gotinha invalido: emotions/transitions ausentes.")

        return GotinhaManifest(
            version=int(data.get("version", 1)),
            emotions={str(key): str(value) for key, value in emotions.items()},
            transitions={
                str(key): [str(frame) for frame in value]
                for key, value in transitions.items()
                if isinstance(value, list)
            },
        )

    def emotion_asset(self, emotion: GotinhaEmotion | str) -> str:
        emotion_key = self._emotion_key(emotion)
        relative_path = self.manifest.emotions.get(emotion_key)
        if not relative_path:
            return self.fallback_asset
        if not self._asset_exists(relative_path):
            return self.fallback_asset
        return self._public_url(relative_path)

    def transition_assets(self, previous: GotinhaEmotion | str, current: GotinhaEmotion | str) -> list[str]:
        transition_key = f"{self._emotion_key(previous)}>{self._emotion_key(current)}"
        return [
            self._public_url(path)
            for path in self.manifest.transitions.get(transition_key, [])
            if self._asset_exists(path)
        ]

    def has_transition(self, previous: GotinhaEmotion | str, current: GotinhaEmotion | str) -> bool:
        return bool(self.transition_assets(previous, current))

    def as_public_payload(self) -> dict[str, Any]:
        return {
            "version": self.manifest.version,
            "fallbackAsset": self.fallback_asset,
            "emotions": {
                emotion.value: self.emotion_asset(emotion)
                for emotion in OFFICIAL_EMOTIONS
            },
            "transitions": {
                key: [self._public_url(path) for path in frames]
                for key, frames in self.manifest.transitions.items()
            },
        }

    def _public_url(self, relative_path: str) -> str:
        if relative_path.startswith(("/", "http://", "https://")):
            return relative_path
        return self.static_prefix + relative_path.lstrip("/")

    def _asset_exists(self, relative_path: str) -> bool:
        if relative_path.startswith(("http://", "https://")):
            return True
        if relative_path.startswith("/static/"):
            candidate = Path("app/static") / relative_path.removeprefix("/static/")
        else:
            candidate = self.manifest_path.parent / relative_path
        return candidate.exists()

    @staticmethod
    def _emotion_key(emotion: GotinhaEmotion | str) -> str:
        return GotinhaEmotion(str(emotion).upper()).value


@dataclass
class GotinhaStateController:
    current_emotion: GotinhaEmotion = GotinhaEmotion.ALEGRIA
    previous_emotion: GotinhaEmotion | None = None
    is_transitioning: bool = False
    registry: GotinhaAssetRegistry = field(default_factory=GotinhaAssetRegistry)

    def set_emotion(self, next_emotion: GotinhaEmotion | str) -> dict[str, Any]:
        next_value = GotinhaEmotion(str(next_emotion).upper())
        if next_value == self.current_emotion and not self.is_transitioning:
            return self.snapshot(transition_frames=[], mode="stable")

        previous = self.current_emotion
        self.previous_emotion = previous
        self.current_emotion = next_value
        transition_frames = self.registry.transition_assets(previous, next_value)
        self.is_transitioning = bool(transition_frames)
        return self.snapshot(
            transition_frames=transition_frames,
            mode="frames" if transition_frames else "crossfade",
        )

    def finish_transition(self) -> None:
        self.is_transitioning = False

    def snapshot(self, transition_frames: list[str] | None = None, mode: str = "stable") -> dict[str, Any]:
        return {
            "previousEmotion": self.previous_emotion.value if self.previous_emotion else None,
            "currentEmotion": self.current_emotion.value,
            "isTransitioning": self.is_transitioning,
            "mode": mode,
            "currentAsset": self.registry.emotion_asset(self.current_emotion),
            "transitionFrames": transition_frames or [],
        }


class GotinhaRuleEngine:
    def suggest_emotion(self, context: dict[str, Any]) -> GotinhaEmotion | None:
        return None

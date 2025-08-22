from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

import numpy as np

try:
	from faster_whisper import WhisperModel
except Exception:  # pragma: no cover - optional at install time
	WhisperModel = None  # type: ignore


@dataclass
class Word:
	text: str
	start: float
	end: float
	confidence: Optional[float]


class Transcriber:
	def __init__(self) -> None:
		self._models: dict[str, WhisperModel] = {}

	def _get_model(self, size: str) -> WhisperModel:
		if WhisperModel is None:
			raise RuntimeError("faster-whisper not installed")
		if size not in self._models:
			self._models[size] = WhisperModel(size, compute_type="int8")
		return self._models[size]

	def transcribe(self, audio_path: str, model_size: str = "small") -> List[Word]:
		model = self._get_model(model_size)
		segments, info = model.transcribe(audio_path, word_timestamps=True)
		words: List[Word] = []
		for seg in segments:
			if not hasattr(seg, "words") or seg.words is None:
				continue
			for w in seg.words:
				conf = getattr(w, "probability", None)
				words.append(Word(text=w.word.strip(), start=float(w.start), end=float(w.end), confidence=None if conf is None else float(conf)))
		return words



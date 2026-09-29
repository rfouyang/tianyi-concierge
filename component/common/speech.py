from __future__ import annotations

import hashlib
import os
import re
import threading
import wave
from collections.abc import Iterable
from pathlib import Path

from util.audio_helper import AudioPlayer, pcm_to_wav, require_robot_wav
from util.byteplus_tts_helper import BytePlusTTS

BASE_DIR = Path(__file__).resolve().parents[2]
DEFAULT_SPEECH_DIR = BASE_DIR / "data" / "tts"
UPLOAD_PATTERN = re.compile(r"^upload_[0-9a-f]{24}\.wav$")
MAX_UPLOAD_BYTES = 20 * 1024 * 1024

# Fixed announcements the executor speaks; prepared ahead of time for offline runs.
ANNOUNCEMENTS = (
    "I am leaving the charging dock.",
    "I have left the charging dock.",
    "I am returning to the charging dock.",
    "I have returned to the charging dock and am charging.",
    "Localization quality is too low. Please manually return me to the charging "
    "dock, then press Resume.",
)


class SpeechService:
    """Store and play speech as robot-format WAV files in data/tts.

    Every clip is 16 kHz, mono, signed 16-bit PCM (the G1 playback format),
    whether BytePlus synthesized it or an operator uploaded it. Synthesis
    happens only while designing a task; tours play prepared files only.
    """

    def __init__(
        self,
        cache_dir: Path | str = DEFAULT_SPEECH_DIR,
        *,
        tts: BytePlusTTS | None = None,
        player: AudioPlayer | None = None,
        speaker: str = "en_female_stokie_uranus_bigtts",
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.speaker = speaker
        self._tts = tts
        self.player = player or AudioPlayer()
        self._lock = threading.Lock()

    def _client(self) -> BytePlusTTS:
        if self._tts is None:
            self._tts = BytePlusTTS(speaker=self.speaker)
        return self._tts

    # ---------------------------------------------------------- synthesized
    def audio_path(self, text: str) -> Path:
        normalized = " ".join(str(text).split())
        digest = hashlib.sha256(f"{self.speaker}\n{normalized}".encode()).hexdigest()
        return self.cache_dir / f"tts_{digest[:24]}.wav"

    def is_cached(self, text: str) -> bool:
        return self.audio_path(text).is_file()

    def missing(self, texts: Iterable[str]) -> list[str]:
        return [text for text in texts if text and not self.is_cached(text)]

    def ensure(self, text: str) -> Path:
        """Return prepared audio for ``text``, synthesizing it only when missing."""
        text = str(text or "").strip()
        if not text:
            raise ValueError("Speech text cannot be empty")
        path = self.audio_path(text)
        if path.is_file():
            return path
        with self._lock:
            if path.is_file():
                return path
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            raw = path.with_suffix(".tmp.pcm")
            try:
                self._client().synthesize_unitree_pcm(text, raw)
                temporary = pcm_to_wav(raw.read_bytes(), path.with_suffix(".tmp.wav"))
            except Exception as error:
                raise RuntimeError(
                    "Speech is not prepared and could not be synthesized "
                    f"(is the network available?): {error}"
                ) from error
            finally:
                raw.unlink(missing_ok=True)
            os.replace(temporary, path)
        return path

    def prepare_all(self, texts: Iterable[str]) -> list[Path]:
        return [self.ensure(text) for text in texts if str(text or "").strip()]

    def require(self, text: str) -> Path:
        """Return prepared audio without synthesizing; tours use only this."""
        path = self.audio_path(text)
        if not path.is_file():
            raise RuntimeError(
                f"Speech is not prepared for: {str(text)[:60]!r}. "
                "Save the task in Task design to prepare it"
            )
        return path

    # -------------------------------------------------------------- uploads
    def store_upload(self, data: bytes) -> dict:
        """Validate an operator's WAV and store it under a content-hash name."""
        if len(data) > MAX_UPLOAD_BYTES:
            raise ValueError("Speech upload is larger than 20 MB")
        info = require_robot_wav(data)
        name = f"upload_{hashlib.sha256(data).hexdigest()[:24]}.wav"
        path = self.cache_dir / name
        if not path.is_file():
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".tmp.wav")
            temporary.write_bytes(data)
            os.replace(temporary, path)
        return {"file": name, "duration": round(info["duration"], 2)}

    def upload_path(self, name: str) -> Path:
        if not UPLOAD_PATTERN.fullmatch(str(name)):
            raise ValueError(f"Invalid uploaded speech name: {name}")
        return self.cache_dir / name

    # ------------------------------------------------------------ per stop
    def stop_audio(self, stop: dict) -> Path:
        """Uploaded speech wins over synthesized speech; neither is created here."""
        if stop.get("audio"):
            path = self.upload_path(stop["audio"])
            if not path.is_file():
                raise RuntimeError(
                    f"Uploaded speech for {stop.get('poi_name', 'this stop')} is missing: "
                    f"data/tts/{stop['audio']}"
                )
            return path
        return self.require(stop["content"])

    @staticmethod
    def duration(path: Path) -> float:
        """Length of a prepared WAV in seconds."""
        with wave.open(str(path), "rb") as wav:
            return round(wav.getnframes() / wav.getframerate(), 1)

    def stop_duration(self, stop: dict) -> float | None:
        try:
            return self.duration(self.stop_audio(stop))
        except (RuntimeError, ValueError, OSError, wave.Error):
            return None

    def stop_ready(self, stop: dict) -> bool:
        try:
            self.stop_audio(stop)
        except (RuntimeError, ValueError):
            return False
        return True

    def prepare(self, task, stop, stop_index):
        """Look up a stop's prepared audio; never synthesizes during a tour."""
        del task, stop_index
        return self.stop_audio(stop)

    # ------------------------------------------------------------- playback
    def play(self, audio_path):
        self.player.play(audio_path)

    def play_cached(self, text: str) -> Path:
        path = self.require(text)
        self.player.play(path)
        return path

    def prepare_text(self, text: str, label: str = "") -> Path:
        del label
        return self.ensure(text)

    def speak(self, text, label=""):
        """Play one announcement, synthesizing it if missing (not used by tours)."""
        audio_path = self.ensure(text)
        self.player.play(audio_path)
        return audio_path

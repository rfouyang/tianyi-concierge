"""Minimal BytePlus text-to-speech client."""

import base64
import json
import os
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path

import requests
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = BASE_DIR / "output"
load_dotenv(BASE_DIR / ".env")


class BytePlusTTS:
    URL = "https://voice.ap-southeast-1.bytepluses.com/api/v3/tts/unidirectional"
    MP3_SAMPLE_RATE = 24000
    UNITREE_SAMPLE_RATE = 16000
    UNITREE_CHANNELS = 1
    UNITREE_BITS_PER_SAMPLE = 16

    def __init__(
        self,
        speaker: str = "en_female_stokie_uranus_bigtts",
    ) -> None:
        self.api_key = os.getenv("BYTEPLUS_API_KEY")
        if not self.api_key:
            raise ValueError("Set BYTEPLUS_API_KEY in the project .env file")

        self.speaker = speaker
        self.session = requests.Session()

    def synthesize_mp3(self, text: str, output_file: str | Path) -> Path:
        """Convert text to an MP3 file."""

        return self._synthesize(text, output_file, "mp3", self.MP3_SAMPLE_RATE)

    def synthesize_unitree_pcm(
        self,
        text: str,
        output_file: str | Path,
        on_audio: Callable[[bytes], None] | None = None,
    ) -> Path:
        """Convert text to Unitree-compatible 16 kHz mono PCM."""

        return self._synthesize(
            text,
            output_file,
            "pcm",
            self.UNITREE_SAMPLE_RATE,
            on_audio,
        )

    def _synthesize(
        self,
        text: str,
        output_file: str | Path,
        audio_format: str,
        sample_rate: int,
        on_audio: Callable[[bytes], None] | None = None,
    ) -> Path:
        """Send one synthesis request and save its audio response."""

        if not text.strip():
            raise ValueError("Text cannot be empty")

        path = Path(output_file)
        expected_suffix = f".{audio_format}"
        if path.suffix.lower() != expected_suffix:
            raise ValueError(f"Output file must use the {expected_suffix} extension")

        response = self.session.post(
            self.URL,
            headers=self._headers(),
            json=self._payload(text, audio_format, sample_rate),
            stream=True,
            timeout=(5, 60),
        )
        audio = bytearray()
        try:
            response.raise_for_status()
            response.encoding = "utf-8"
            for event in self._events(response):
                code = event.get("code", 0)
                if code == 20000000:
                    break
                if code != 0:
                    raise RuntimeError(f"BytePlus TTS failed: {event.get('message')}")
                if event.get("data"):
                    chunk = base64.b64decode(event["data"])
                    audio.extend(chunk)
                    if on_audio:
                        on_audio(chunk)
        finally:
            response.close()

        if not audio:
            raise RuntimeError("BytePlus returned no audio")

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(audio)
        return path

    def _headers(self) -> dict[str, str]:
        return {
            "X-Api-Key": self.api_key,
            "X-Api-Resource-Id": "seed-tts-2.0",
            "X-Api-Request-Id": str(uuid.uuid4()),
            "Content-Type": "application/json",
        }

    def _payload(self, text: str, audio_format: str, sample_rate: int) -> dict:
        additions = {
            "disable_markdown_filter": True,
            "enable_language_detector": True,
            "enable_latex_tn": True,
            "disable_default_bit_rate": True,
            "max_length_to_filter_parenthesis": 0,
            "cache_config": {"text_type": 1, "use_cache": True},
        }
        return {
            "req_params": {
                "text": text,
                "speaker": self.speaker,
                "additions": json.dumps(additions),
                "audio_params": {
                    "format": audio_format,
                    "sample_rate": sample_rate,
                },
            }
        }

    @staticmethod
    def _events(response: requests.Response) -> Iterator[dict]:
        """Read JSON objects from the streaming response."""

        decoder = json.JSONDecoder()
        buffer = ""

        for chunk in response.iter_content(chunk_size=4096, decode_unicode=True):
            buffer += chunk
            while buffer.strip():
                try:
                    event, end = decoder.raw_decode(buffer.lstrip())
                except json.JSONDecodeError:
                    break
                yield event
                buffer = buffer.lstrip()[end:]


def demo_mp3() -> None:
    """Generate the demo MP3 file."""

    tts = BytePlusTTS()
    output = tts.synthesize_mp3(
        "To be or not to be, that is the question.",
        OUTPUT_DIR / "byteplus_demo.mp3",
    )
    print(f"MP3 saved to {output.resolve()}")


def demo_pcm() -> None:
    """Generate the demo 16 kHz mono PCM file."""

    tts = BytePlusTTS()
    output = tts.synthesize_unitree_pcm(
        "To be or not to be, that is the question.",
        OUTPUT_DIR / "byteplus_demo.pcm",
    )
    print(f"PCM saved to {output.resolve()}")


def main() -> None:
    demo_mp3()
    demo_pcm()


if __name__ == "__main__":
    main()

import io
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import Mock

from component.common.speech import SpeechService


def robot_wav(rate=16000, channels=1, width=2, frames=1600):
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(width)
        wav.setframerate(rate)
        wav.writeframes(b"\x00" * frames * channels * width)
    return buffer.getvalue()


class FakeTts:
    def __init__(self, fail=False):
        self.fail = fail
        self.calls = []

    def synthesize_unitree_pcm(self, text, output_file):
        if self.fail:
            raise ConnectionError("network unreachable")
        self.calls.append(text)
        Path(output_file).write_bytes(b"\x01\x00" * 1600)
        return Path(output_file)


class SpeechServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.tts = FakeTts()
        self.player = Mock()
        self.speech = SpeechService(Path(self.temporary.name), tts=self.tts, player=self.player)

    def tearDown(self):
        self.temporary.cleanup()

    def test_speech_is_synthesized_once_per_text(self):
        first = self.speech.ensure("Welcome to the lab.")
        second = self.speech.ensure("Welcome   to the lab.")

        self.assertEqual(first, second)
        self.assertEqual(self.tts.calls, ["Welcome to the lab."])

    def test_synthesized_speech_uses_the_robot_wav_format(self):
        path = self.speech.ensure("Hello")

        with wave.open(str(path)) as wav:
            self.assertEqual(
                (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()), (16000, 1, 2)
            )

    def test_tours_never_synthesize(self):
        with self.assertRaisesRegex(RuntimeError, "not prepared"):
            self.speech.prepare({}, {"content": "Unprepared", "poi_name": "Hall"}, 1)

        self.assertEqual(self.tts.calls, [])

    def test_offline_synthesis_reports_a_clear_error(self):
        speech = SpeechService(
            Path(self.temporary.name), tts=FakeTts(fail=True), player=self.player
        )

        with self.assertRaisesRegex(RuntimeError, "network"):
            speech.ensure("Hello")
        self.assertFalse(speech.is_cached("Hello"))

    def test_upload_accepts_16k_mono_16bit_wav(self):
        stored = self.speech.store_upload(robot_wav())

        self.assertRegex(stored["file"], r"^upload_[0-9a-f]{24}\.wav$")
        self.assertEqual(stored["duration"], 0.1)
        path = self.speech.stop_audio({"audio": stored["file"], "content": "Transcript"})
        self.assertTrue(path.is_file())

    def test_upload_rejects_other_formats_with_reasons(self):
        with self.assertRaisesRegex(ValueError, "44100 Hz.*2 channels"):
            self.speech.store_upload(robot_wav(rate=44100, channels=2))
        with self.assertRaisesRegex(ValueError, "8-bit"):
            self.speech.store_upload(robot_wav(width=1))
        with self.assertRaisesRegex(ValueError, "not a PCM WAV"):
            self.speech.store_upload(b"ID3 not a wav")

    def test_uploaded_speech_wins_over_text(self):
        stored = self.speech.store_upload(robot_wav())

        path = self.speech.stop_audio({"audio": stored["file"], "content": "Never synthesized"})

        self.assertEqual(path.name, stored["file"])
        self.assertEqual(self.tts.calls, [])

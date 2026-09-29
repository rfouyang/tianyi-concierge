"""Cross-platform MP3 and raw PCM playback helpers."""

import io
import time
import wave
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = BASE_DIR / "output"


# Tianyi plays speech in the same format as G1: 16 kHz, mono, signed 16-bit PCM.
ROBOT_SAMPLE_RATE = 16000
ROBOT_CHANNELS = 1
ROBOT_SAMPLE_WIDTH = 2


def inspect_wav(data: bytes) -> dict:
    """Read a WAV header; raise ValueError if the bytes are not a PCM WAV."""
    try:
        with wave.open(io.BytesIO(data), "rb") as wav:
            info = {
                "sample_rate": wav.getframerate(),
                "channels": wav.getnchannels(),
                "sample_width": wav.getsampwidth(),
                "frames": wav.getnframes(),
                "compression": wav.getcomptype(),
            }
    except (wave.Error, EOFError) as error:
        raise ValueError(f"File is not a PCM WAV: {error}") from error
    info["duration"] = info["frames"] / info["sample_rate"] if info["sample_rate"] else 0.0
    return info


def require_robot_wav(data: bytes) -> dict:
    """Accept only 16 kHz, mono, 16-bit PCM WAV (the G1 playback format)."""
    info = inspect_wav(data)
    problems = []
    if info["compression"] != "NONE":
        problems.append(f"compression {info['compression']} (needs uncompressed PCM)")
    if info["sample_rate"] != ROBOT_SAMPLE_RATE:
        problems.append(f"{info['sample_rate']} Hz (needs {ROBOT_SAMPLE_RATE} Hz)")
    if info["channels"] != ROBOT_CHANNELS:
        problems.append(f"{info['channels']} channels (needs mono)")
    if info["sample_width"] != ROBOT_SAMPLE_WIDTH:
        problems.append(f"{info['sample_width'] * 8}-bit (needs 16-bit)")
    if info["frames"] == 0:
        problems.append("no audio frames")
    if problems:
        raise ValueError("WAV does not match the robot format: " + ", ".join(problems))
    return info


def pcm_to_wav(
    pcm: bytes, output_file: str | Path, *, sample_rate: int = ROBOT_SAMPLE_RATE
) -> Path:
    """Wrap signed 16-bit mono PCM in a WAV container."""
    path = Path(output_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(ROBOT_CHANNELS)
        wav.setsampwidth(ROBOT_SAMPLE_WIDTH)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm)
    return path


class PCMStream:
    """Persistent low-latency stream for signed 16-bit PCM audio."""

    def __init__(self, sample_rate: int = 16000, channels: int = 1) -> None:
        import sounddevice as sd

        self.stream = sd.RawOutputStream(
            samplerate=sample_rate,
            channels=channels,
            dtype="int16",
            latency="low",
        )

    def __enter__(self) -> "PCMStream":
        self.stream.start()
        return self

    def write(self, pcm: bytes) -> None:
        """Play one raw PCM chunk."""

        self.stream.write(pcm)

    def play_file(self, audio_file: str | Path) -> None:
        """Play a raw PCM file through the open stream."""

        path = Path(audio_file)
        with path.open("rb") as file:
            while chunk := file.read(4096):
                self.write(chunk)

    def __exit__(self, *_: object) -> None:
        self.stream.stop()
        self.stream.close()


class AudioPlayer:
    """Play MP3, WAV, or signed 16-bit raw PCM audio files."""

    def play(
        self,
        audio_file: str | Path,
        *,
        sample_rate: int = 16000,
        channels: int = 1,
    ) -> None:
        path = Path(audio_file)
        if path.suffix.lower() in {".mp3", ".wav"}:
            self.play_encoded(path)
        elif path.suffix.lower() == ".pcm":
            self.play_pcm(path, sample_rate=sample_rate, channels=channels)
        else:
            raise ValueError(f"Unsupported audio file: {path}")

    @staticmethod
    def play_mp3(audio_file: str | Path) -> None:
        """Decode and play an MP3 file with miniaudio."""

        AudioPlayer.play_encoded(audio_file)

    @staticmethod
    def play_encoded(audio_file: str | Path) -> None:
        """Decode and play an MP3 or WAV file with miniaudio."""

        import miniaudio

        path = Path(audio_file)
        stream = miniaudio.stream_file(str(path))
        with miniaudio.PlaybackDevice(buffersize_msec=100) as device:
            device.start(stream)
            while device.callback_generator is not None:
                time.sleep(0.01)
            time.sleep(device.buffersize_msec / 1000)

    @staticmethod
    def play_pcm(
        audio_file: str | Path,
        *,
        sample_rate: int = 16000,
        channels: int = 1,
    ) -> None:
        """Play a signed 16-bit raw PCM file."""

        with PCMStream(sample_rate, channels) as stream:
            stream.play_file(audio_file)


def demo_mp3() -> None:
    """Play the demo MP3 file."""

    AudioPlayer().play_mp3(OUTPUT_DIR / "byteplus_demo.mp3")


def demo_pcm() -> None:
    """Play the 16 kHz mono PCM file generated by BytePlusTTS."""

    AudioPlayer().play_pcm(OUTPUT_DIR / "byteplus_demo.pcm")


def main() -> None:
    demo_mp3()
    demo_pcm()


if __name__ == "__main__":
    main()

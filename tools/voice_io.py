"""
Voice I/O — mic input (SpeechRecognition) + TTS output (pyttsx3).

Both are optional; missing engines degrade gracefully with clear errors
instead of crashing the UI.
"""

from __future__ import annotations

import threading
from typing import Callable

try:
    import speech_recognition as sr  # type: ignore
    _SR_OK = True
except Exception:
    _SR_OK = False

try:
    import pyttsx3  # type: ignore
    _TTS_OK = True
except Exception:
    _TTS_OK = False


_tts_lock = threading.Lock()
_tts_engine = None


def _get_tts():
    global _tts_engine
    if not _TTS_OK:
        return None
    if _tts_engine is None:
        _tts_engine = pyttsx3.init()
        _tts_engine.setProperty("rate", 180)
    return _tts_engine


# ── Input ────────────────────────────────────────────────────────────────────

def listen_once(
    timeout: float = 5.0,
    phrase_time_limit: float = 15.0,
    language: str = "en-US",
) -> str:
    """
    Record from the default microphone once and return the transcription.
    Returns an empty string on any failure (so the UI can no-op gracefully).
    """
    if not _SR_OK:
        return ""
    try:
        recognizer = sr.Recognizer()
        with sr.Microphone() as source:
            recognizer.adjust_for_ambient_noise(source, duration=0.4)
            audio = recognizer.listen(source, timeout=timeout, phrase_time_limit=phrase_time_limit)
        try:
            return recognizer.recognize_google(audio, language=language) or ""
        except Exception:
            return ""
    except Exception as e:
        print(f"[VoiceIO] listen failed: {e}")
        return ""


def is_microphone_available() -> bool:
    if not _SR_OK:
        return False
    try:
        sr.Microphone.list_microphone_names()
        return True
    except Exception:
        return False


# ── Output ───────────────────────────────────────────────────────────────────

def speak(text: str, *, rate: int | None = None, blocking: bool = False) -> bool:
    """Pipe `text` through the local TTS engine. Returns True on success."""
    engine = _get_tts()
    if engine is None or not text:
        return False

    def _run() -> None:
        with _tts_lock:
            if rate is not None:
                engine.setProperty("rate", rate)
            engine.say(text)
            engine.runAndWait()

    if blocking:
        _run()
    else:
        threading.Thread(target=_run, daemon=True, name="MetisTTS").start()
    return True


def stop_speaking() -> None:
    engine = _get_tts()
    if engine is not None:
        try:
            engine.stop()
        except Exception:
            pass


# ── CrewAI tool registration ─────────────────────────────────────────────────

def as_crewai_tools():
    try:
        from crewai.tools import tool  # type: ignore
    except Exception:
        return []

    @tool("Speak")
    def _speak_tool(text: str) -> str:
        """Speak the provided text aloud on the Director's machine."""
        return "ok" if speak(text) else "tts-unavailable"

    @tool("ListenOnce")
    def _listen_tool() -> str:
        """Record a single mic phrase and return the transcription."""
        return listen_once()

    return [_speak_tool, _listen_tool]

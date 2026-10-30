# voice/ — Phase 2 (not implemented yet)

Planned modules and their single responsibility:

| File | Responsibility |
|---|---|
| `microphone.py` | push-to-talk capture (sounddevice); no always-on recording in v1 |
| `speech_to_text.py` | faster-whisper, model loaded lazily on first activation |
| `text_to_speech.py` | pyttsx3 / Windows SAPI wrapper (see `core/response_engine.py`) |
| `wake_word.py` | openWakeWord "hey jarvis" → arms a 6 s listening window |
| `voice_auth.py` | speaker verification — **advisory only, never a password** |

Integration contract: after STT, call
`JarvisAgent.handle_text(text, source=CommandSource.LOCAL_VOICE)`.
Nothing in the parser, validator, permission engine or executor changes.

"""
A.R.C.H.I.E. Voice DNA System
Phase 64: Emotion-modulated speech synthesis with phoneme-based caching

Gives A.R.C.H.I.E. her unique voice that reflects her emotional state and personality.
Uses Coqui TTS with XTTS v2 model for high-quality, warm feminine voice synthesis.

Phoneme-Based Caching Strategy:
- Extract phonemes from text using gruut
- Cache individual words with their phoneme sequences
- Assemble phrases by concatenating cached word audio
- Store phoneme audio in voice_phoneme_library for reference
"""

import os

# Apply XTTS compatibility patches BEFORE any TTS/torch imports
# Fixes: torch.load weights_only default (torch>=2.6) + BeamSearchScorer removal (transformers>=4.45)
from xtts_compat import apply_patches as _apply_xtts_patches

_apply_xtts_patches()

from db import _get_db_password
import io
import base64
import hashlib
import time
import json
import re
from typing import Optional, Dict, Any, List, Tuple
import psycopg2
from psycopg2.extras import RealDictCursor


def normalize_text_for_tts(text: str) -> str:
    """Normalize text for natural TTS pronunciation."""
    # ARCHIE acronym — case-insensitive
    text = re.sub(r"A\.R\.C\.H\.I\.E\.?", "ARCHIE", text, flags=re.IGNORECASE)
    # Titles (careful: "Dr." ends with period that could be sentence boundary)
    text = re.sub(r"\bDr\.(?=\s)", "Doctor", text)
    text = re.sub(r"\bMr\.(?=\s)", "Mister", text)
    text = re.sub(r"\bMrs\.(?=\s)", "Missus", text)
    text = re.sub(r"\bMs\.(?=\s)", "Miss", text)
    # Common abbreviations
    text = re.sub(r"\betc\.", "etcetera", text, flags=re.IGNORECASE)
    text = re.sub(r"\bi\.e\.", "that is", text, flags=re.IGNORECASE)
    text = re.sub(r"\be\.g\.", "for example", text, flags=re.IGNORECASE)
    text = re.sub(r"\bvs\.", "versus", text, flags=re.IGNORECASE)
    # Strip markdown emphasis (*bold*, _italic_)
    text = re.sub(r"\*{1,2}([^*]+)\*{1,2}", r"\1", text)
    text = re.sub(r"_{1,2}([^_]+)_{1,2}", r"\1", text)
    # Strip markdown headers
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    # Strip bullet points
    text = re.sub(r"^[-*]\s+", "", text, flags=re.MULTILINE)
    return text


def split_into_sentences(text: str, max_chunk: int = 500) -> list:
    """Split text into sentence-boundary chunks, each <=max_chunk chars."""
    # Split on sentence-ending punctuation followed by space
    parts = re.split(r"([.!?]+)\s+", text)
    # Rejoin punctuation with preceding sentence
    sentences = []
    for i in range(0, len(parts), 2):
        s = parts[i]
        if i + 1 < len(parts):
            s += parts[i + 1]
        s = s.strip()
        if s:
            sentences.append(s)
    # Batch small sentences together up to max_chunk
    chunks = []
    current = ""
    for s in sentences:
        if len(s) > max_chunk:
            if current:
                chunks.append(current)
                current = ""
            chunks.append(s[:max_chunk])
        elif len(current) + len(s) + 1 <= max_chunk:
            current = (current + " " + s).strip()
        else:
            if current:
                chunks.append(current)
            current = s
    if current:
        chunks.append(current)
    return chunks if chunks else [text[:max_chunk]]


class PhonemeExtractor:
    """
    Extract IPA phonemes from text using gruut.
    Used for phoneme-based voice caching and word assembly.
    """

    def __init__(self):
        self._gruut_available = None

    def _check_gruut(self) -> bool:
        """Check if gruut is available"""
        if self._gruut_available is None:
            try:
                from gruut import sentences

                self._gruut_available = True
            except ImportError:
                print("[VoiceDNA] gruut not available for phoneme extraction")
                self._gruut_available = False
        return self._gruut_available

    def extract_phonemes(self, text: str, lang: str = "en-us") -> List[Dict[str, Any]]:
        """
        Extract phonemes from text.

        Args:
            text: Text to extract phonemes from
            lang: Language code (default: en-us)

        Returns:
            List of word dicts with 'word', 'phonemes', 'ipa' keys
        """
        if not self._check_gruut():
            return []

        from gruut import sentences

        words = []
        for sent in sentences(text, lang=lang):
            for word in sent:
                if word.text.strip():
                    phonemes = word.phonemes if word.phonemes else []
                    words.append(
                        {
                            "word": word.text,
                            "phonemes": phonemes,
                            "ipa": "".join(phonemes),
                            "is_punctuation": (word.is_punctuation if hasattr(word, "is_punctuation") else False),
                        }
                    )
        return words

    def text_to_words(self, text: str) -> List[str]:
        """
        Split text into words, preserving punctuation separately.

        Args:
            text: Text to split

        Returns:
            List of words (punctuation as separate tokens)
        """
        # Split on whitespace, keeping punctuation attached
        tokens = []
        for word in text.split():
            # Separate leading punctuation
            while word and word[0] in ".,!?;:\"'-(":
                tokens.append(word[0])
                word = word[1:]
            # Separate trailing punctuation
            trailing = []
            while word and word[-1] in ".,!?;:\"'-()":
                trailing.insert(0, word[-1])
                word = word[:-1]
            if word:
                tokens.append(word)
            tokens.extend(trailing)
        return tokens

    def get_word_hash(self, word: str, emotion: str) -> str:
        """Generate cache key for a word+emotion combination"""
        content = f"word:{word.lower()}|{emotion}"
        return hashlib.sha256(content.encode()).hexdigest()[:32]


# Global phoneme extractor instance
_phoneme_extractor = None


def get_phoneme_extractor() -> PhonemeExtractor:
    """Get or create phoneme extractor singleton"""
    global _phoneme_extractor
    if _phoneme_extractor is None:
        _phoneme_extractor = PhonemeExtractor()
    return _phoneme_extractor


class KokoroEngine:
    """Kokoro-82M TTS engine — fast, multi-voice, supports blending"""

    ENGINE_NAME = "kokoro"

    VOICES = {
        "American English Female": [
            "af_alloy",
            "af_aoede",
            "af_bella",
            "af_heart",
            "af_jessica",
            "af_kore",
            "af_nicole",
            "af_nova",
            "af_river",
            "af_sarah",
            "af_sky",
        ],
        "American English Male": [
            "am_adam",
            "am_echo",
            "am_eric",
            "am_fenrir",
            "am_liam",
            "am_michael",
            "am_onyx",
            "am_puck",
            "am_santa",
        ],
        "British English Female": ["bf_alice", "bf_emma", "bf_isabella", "bf_lily"],
        "British English Male": ["bm_daniel", "bm_fable", "bm_george", "bm_lewis"],
    }
    DEFAULT_VOICE = "af_heart"

    def __init__(self):
        self._pipelines = {}  # lang_code -> KPipeline
        self._loaded = False
        self._available = None  # None = unchecked, True/False = checked

    @staticmethod
    def check_available():
        """Check if kokoro package is installed"""
        try:
            import kokoro  # noqa: F401

            return True
        except ImportError:
            return False

    def _get_pipeline(self, voice):
        """Get or create pipeline for the voice's language"""
        if self._available is None:
            self._available = self.check_available()
        if not self._available:
            raise ImportError("Kokoro package not installed. Run: pip install kokoro>=0.9.4")

        lang = "b" if (voice or "").startswith("b") else "a"
        if lang not in self._pipelines:
            from kokoro import KPipeline

            self._pipelines[lang] = KPipeline(lang_code=lang)
            self._loaded = True
        return self._pipelines[lang]

    def synthesize_to_wav(self, text, voice=None, speed=1.0, voice_blend=None):
        """Synthesize text to WAV bytes (24kHz)

        voice_blend: Comma-separated voice names for blending.
            Kokoro averages the voice tensors equally.
            Weight annotations (e.g. 'af_bella:60,am_adam:40') are accepted
            but stripped — Kokoro only supports equal-weight blending.
        """
        import numpy as np
        import soundfile as sf

        if voice_blend:
            # Strip weight annotations: "af_bella:60,am_adam:40" -> "af_bella,am_adam"
            parts = [v.split(":")[0].strip() for v in voice_blend.split(",") if v.strip()]
            voice = ",".join(parts) if parts else voice or self.DEFAULT_VOICE
        else:
            voice = voice or self.DEFAULT_VOICE
        pipeline = self._get_pipeline(voice)

        chunks = []
        for gs, ps, audio in pipeline(text, voice=voice, speed=speed):
            chunks.append(audio)

        if not chunks:
            raise RuntimeError("Kokoro produced no audio")

        full_audio = np.concatenate(chunks)
        buf = io.BytesIO()
        sf.write(buf, full_audio, 24000, format="WAV")
        return buf.getvalue()

    def get_speakers(self):
        """Return flat list of all voice IDs"""
        voices = []
        for group in self.VOICES.values():
            voices.extend(group)
        return voices

    def get_speakers_grouped(self):
        """Return voices grouped by category"""
        return dict(self.VOICES)

    @property
    def is_loaded(self):
        return self._loaded


class VoiceSynthesizer:
    """Voice synthesis with emotion modulation for A.R.C.H.I.E."""

    # Built-in XTTS v2 speakers - Ana Florence is warm, professional feminine
    DEFAULT_SPEAKER = "Ana Florence"

    # Fallback if Ana Florence not available
    FALLBACK_SPEAKERS = ["Annmarie Nele", "Suad Qasim", "Tammie Ema"]

    # Quality presets for XTTS v2 inference
    # These kwargs are passed through tts_to_file → model.inference
    # Lower temperature = more stable/consistent output
    # Higher repetition_penalty = less stuttering
    # Lower top_p/top_k = more predictable, cleaner audio
    QUALITY_PRESETS = {
        "standard": {
            # Default XTTS v2 settings — fast, good enough for real-time
            "temperature": 0.75,
            "top_k": 50,
            "top_p": 0.85,
            "repetition_penalty": 10.0,
        },
        "high": {
            # Lower temperature for more stable, cleaner synthesis
            # Tighter sampling for less random artifacts
            # Better for pre-generation where speed doesn't matter
            "temperature": 0.35,
            "top_k": 30,
            "top_p": 0.65,
            "repetition_penalty": 12.0,
        },
    }

    # Emotion-to-voice parameter mapping
    # speed: 0.5-2.0 (1.0 = normal)
    # pitch_shift: 0.8-1.2 (1.0 = no shift)
    # warmth: 0.0-1.0 (affects tone)
    EMOTION_VOICE_MAP = {
        "excited": {"speed": 1.10, "pitch_shift": 1.05, "warmth": 0.90},
        "curious": {"speed": 1.00, "pitch_shift": 1.02, "warmth": 0.85},
        "empathetic": {"speed": 0.90, "pitch_shift": 0.98, "warmth": 0.95},
        "focused": {"speed": 0.95, "pitch_shift": 1.00, "warmth": 0.75},
        "playful": {"speed": 1.05, "pitch_shift": 1.03, "warmth": 0.88},
        "concerned": {"speed": 0.88, "pitch_shift": 0.97, "warmth": 0.92},
        "thoughtful": {"speed": 0.92, "pitch_shift": 0.99, "warmth": 0.82},
        "confident": {"speed": 1.02, "pitch_shift": 1.01, "warmth": 0.80},
        "gentle": {"speed": 0.88, "pitch_shift": 0.98, "warmth": 0.95},
        "neutral": {"speed": 1.00, "pitch_shift": 1.00, "warmth": 0.80},
    }

    def __init__(self, lazy_init: bool = True):
        """
        Initialize VoiceSynthesizer.

        Args:
            lazy_init: If True, TTS model loads on first use (saves startup time)
        """
        self.tts = None
        self._available_speakers = []
        self._model_loaded = False
        self._kokoro = None  # Lazy-loaded KokoroEngine

        if not lazy_init:
            self._init_tts()

    def _init_tts(self):
        """Initialize Coqui TTS with XTTS v2 model"""
        if self._model_loaded:
            return

        try:
            # Auto-accept Coqui license (CPML for non-commercial use)
            os.environ["COQUI_TOS_AGREED"] = "1"

            from TTS.api import TTS

            print("[VoiceDNA] Initializing Coqui TTS with XTTS v2...")

            # XTTS v2 supports multiple speakers and languages
            # First run downloads ~1.5GB model
            self.tts = TTS("tts_models/multilingual/multi-dataset/xtts_v2")

            # GPU auto-detection: check for available VRAM
            device = os.getenv("TTS_DEVICE", "auto")
            if device == "auto":
                try:
                    import torch

                    if torch.cuda.is_available():
                        props = torch.cuda.get_device_properties(0)
                        free_mem = props.total_mem - torch.cuda.memory_allocated(0)
                        if free_mem > 1_000_000_000:  # >1GB free VRAM
                            device = "cuda"
                            print(f"[VoiceDNA] GPU detected: {props.name}, {free_mem / 1e9:.1f}GB free → using CUDA")
                        else:
                            device = "cpu"
                            print(f"[VoiceDNA] GPU low VRAM ({free_mem / 1e9:.1f}GB free) → using CPU")
                    else:
                        device = "cpu"
                        print("[VoiceDNA] No CUDA GPU available → using CPU")
                except Exception as e:
                    device = "cpu"
                    print(f"[VoiceDNA] GPU detection failed: {e} → using CPU")
            self.tts.to(device)
            print(f"[VoiceDNA] TTS device: {device}")

            # Get available speakers
            if hasattr(self.tts, "speakers"):
                self._available_speakers = self.tts.speakers or []
                print(f"[VoiceDNA] Available speakers: {len(self._available_speakers)}")

            self._model_loaded = True
            print("[VoiceDNA] TTS initialized successfully")

        except ImportError:
            print("[VoiceDNA] TTS package not installed. Run: pip install TTS>=0.22.0")
            self.tts = None
        except Exception as e:
            print(f"[VoiceDNA] TTS initialization failed: {e}")
            self.tts = None

    def _get_kokoro(self):
        """Get or create lazy-loaded KokoroEngine"""
        if self._kokoro is None:
            self._kokoro = KokoroEngine()
        return self._kokoro

    def synthesize(
        self,
        text: str,
        emotion: str = "neutral",
        user_id: Optional[int] = None,
        quality: str = "standard",
        engine: str = "kokoro",
        language: str = "en",
    ) -> Dict[str, Any]:
        """
        Generate speech from text with emotion modulation.

        Args:
            text: Text to synthesize (max 500 chars)
            emotion: Emotional tone ('excited', 'curious', 'empathetic', etc.)
            user_id: User ID for logging and personalization
            quality: Quality preset ('standard' or 'high')
            engine: TTS engine ('kokoro' or 'xtts_v2')
            language: Language code ('en', 'fr', etc.)

        Returns:
            Dict with success, audio_base64, cached, emotion, parameters
        """
        # Validate input
        if not text or not text.strip():
            return {"success": False, "error": "No text provided"}

        text = normalize_text_for_tts(text.strip())
        if len(text) > 500:
            text = text[:500]

        # Kokoro is English-only; auto-route non-English to XTTS v2
        if language != "en" and engine == "kokoro":
            engine = "xtts_v2"

        # Check cache first (engine+language-scoped key)
        cache_key = self._get_cache_key(text, emotion, engine=engine, language=language)
        cached_audio = self._check_cache(cache_key)
        if cached_audio:
            self._log_generation(
                user_id,
                len(text),
                emotion,
                cached=True,
                time_ms=0,
                engine=engine,
                language=language,
            )
            return {
                "success": True,
                "audio_base64": cached_audio,
                "cached": True,
                "emotion": emotion,
            }

        # Get voice parameters for emotion
        params = self.EMOTION_VOICE_MAP.get(emotion, self.EMOTION_VOICE_MAP["neutral"])

        start_time = time.time()

        try:
            if engine == "kokoro":
                kokoro = self._get_kokoro()
                audio_bytes = kokoro.synthesize_to_wav(text, speed=params["speed"])
                audio_base64 = base64.b64encode(audio_bytes).decode("utf-8")
                speaker = KokoroEngine.DEFAULT_VOICE
            else:
                # XTTS v2 path
                if not self._model_loaded:
                    self._init_tts()
                if not self.tts:
                    return {
                        "success": False,
                        "error": "TTS not available. Install with: pip install TTS>=0.22.0",
                    }

                speaker = self._select_speaker()
                import tempfile

                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_file:
                    temp_path = temp_file.name

                quality_kwargs = self.QUALITY_PRESETS.get(quality, self.QUALITY_PRESETS["standard"])
                self.tts.tts_to_file(
                    text=text,
                    speaker=speaker,
                    language=language,
                    file_path=temp_path,
                    speed=params["speed"],
                    **quality_kwargs,
                )

                with open(temp_path, "rb") as f:
                    audio_bytes = f.read()
                os.unlink(temp_path)
                audio_base64 = base64.b64encode(audio_bytes).decode("utf-8")

            generation_time = int((time.time() - start_time) * 1000)

            self._save_to_cache(
                cache_key,
                text,
                emotion,
                audio_base64,
                params,
                generation_time,
                engine=engine,
                language=language,
            )
            self._log_generation(
                user_id,
                len(text),
                emotion,
                cached=False,
                time_ms=generation_time,
                engine=engine,
                language=language,
            )

            return {
                "success": True,
                "audio_base64": audio_base64,
                "cached": False,
                "emotion": emotion,
                "parameters": params,
                "speaker": speaker,
                "engine": engine,
                "generation_time_ms": generation_time,
            }

        except Exception as e:
            print(f"[VoiceDNA] Synthesis error ({engine}): {e}")
            return {"success": False, "error": str(e)}

    def _select_speaker(self) -> str:
        """Select the best available speaker"""
        if not self._available_speakers:
            return self.DEFAULT_SPEAKER

        # Prefer Ana Florence
        if self.DEFAULT_SPEAKER in self._available_speakers:
            return self.DEFAULT_SPEAKER

        # Try fallbacks
        for fallback in self.FALLBACK_SPEAKERS:
            if fallback in self._available_speakers:
                return fallback

        # Use first available
        return self._available_speakers[0] if self._available_speakers else self.DEFAULT_SPEAKER

    def _get_cache_key(self, text: str, emotion: str, engine: str = "kokoro", language: str = "en") -> str:
        """Generate cache key from text, emotion, engine, and language.
        Text is lowercased to ensure pregen cache hits match runtime synthesis."""
        normalized = text.lower().strip()
        if engine == "kokoro":
            content = f"kokoro|{language}|{normalized}|{emotion}|{KokoroEngine.DEFAULT_VOICE}"
        else:
            speaker = self._select_speaker()
            content = f"xtts_v2|{language}|{normalized}|{emotion}|{speaker}"
        return hashlib.sha256(content.encode()).hexdigest()[:32]

    def _check_cache(self, cache_key: str) -> Optional[str]:
        """Check voice_word_cache for existing audio"""
        try:
            conn = self._get_db()
            try:
                cur = conn.cursor()

                # Update hit count and return audio if exists
                # Using correct column names: full_audio_cache, usage_count, last_used
                cur.execute(
                    """
                    UPDATE voice_word_cache
                    SET hit_count = COALESCE(hit_count, 0) + 1,
                        usage_count = COALESCE(usage_count, 0) + 1,
                        last_used = NOW()
                    WHERE text_hash = %s
                    RETURNING full_audio_cache
                """,
                    (cache_key,),
                )

                result = cur.fetchone()
                conn.commit()

                # full_audio_cache is bytea, need to decode if it's base64 stored as text
                if result and result[0]:
                    cached = result[0]
                    # If it's bytes (bytea), decode to string
                    if isinstance(cached, (bytes, memoryview)):
                        return cached.decode("utf-8") if isinstance(cached, bytes) else bytes(cached).decode("utf-8")
                    return cached
                return None
            finally:
                try:
                    cur.close()
                except Exception:
                    pass
                try:
                    conn.close()
                except Exception:
                    pass

        except Exception as e:
            print(f"[VoiceDNA] Cache check error: {e}")
            return None

    def _save_to_cache(
        self,
        cache_key: str,
        text: str,
        emotion: str,
        audio_base64: str,
        params: dict,
        duration_ms: int,
        engine: str = "kokoro",
        language: str = "en",
    ):
        """Save generated audio to cache"""
        try:
            conn = self._get_db()
            try:
                cur = conn.cursor()

                cur.execute(
                    """
                    INSERT INTO voice_word_cache
                    (word_text, phoneme_sequence, full_audio_cache, text_hash, emotion_context, voice_parameters, duration_ms, hit_count, usage_count, last_used, engine, language)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, 0, 0, NOW(), %s, %s)
                    ON CONFLICT (text_hash) WHERE text_hash IS NOT NULL DO UPDATE
                    SET full_audio_cache = CASE WHEN voice_word_cache.is_locked THEN voice_word_cache.full_audio_cache ELSE EXCLUDED.full_audio_cache END,
                        hit_count = COALESCE(voice_word_cache.hit_count, 0) + 1,
                        usage_count = COALESCE(voice_word_cache.usage_count, 0) + 1,
                        last_used = NOW(),
                        emotion_context = CASE WHEN voice_word_cache.is_locked THEN voice_word_cache.emotion_context ELSE EXCLUDED.emotion_context END,
                        voice_parameters = CASE WHEN voice_word_cache.is_locked THEN voice_word_cache.voice_parameters ELSE EXCLUDED.voice_parameters END,
                        engine = CASE WHEN voice_word_cache.is_locked THEN voice_word_cache.engine ELSE EXCLUDED.engine END,
                        language = CASE WHEN voice_word_cache.is_locked THEN voice_word_cache.language ELSE EXCLUDED.language END
                """,
                    (
                        text[:100],
                        json.dumps([]),
                        audio_base64.encode("utf-8"),
                        cache_key,
                        emotion,
                        json.dumps(params),
                        duration_ms,
                        engine,
                        language,
                    ),
                )

                conn.commit()
            finally:
                try:
                    cur.close()
                except Exception:
                    pass
                try:
                    conn.close()
                except Exception:
                    pass

        except Exception as e:
            print(f"[VoiceDNA] Cache save error: {e}")

    def _log_generation(
        self,
        user_id: Optional[int],
        text_length: int,
        emotion: str,
        cached: bool,
        time_ms: int,
        engine: str = None,
        language: str = "en",
    ):
        """Log voice generation for analytics"""
        try:
            conn = self._get_db()
            try:
                cur = conn.cursor()

                cur.execute(
                    """
                    INSERT INTO voice_generation_log
                    (user_id, text_length, emotion, cached, generation_time_ms, engine, language)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                    (user_id, text_length, emotion, cached, time_ms, engine, language),
                )

                conn.commit()
            finally:
                try:
                    cur.close()
                except Exception:
                    pass
                try:
                    conn.close()
                except Exception:
                    pass

        except Exception as e:
            # Don't fail on logging errors
            print(f"[VoiceDNA] Log error: {e}")

    def _get_db(self):
        """Get database connection"""
        return psycopg2.connect(
            host=os.getenv("DB_HOST", "archie_database"),
            port=os.getenv("DB_PORT", "5432"),
            database=os.getenv("DB_NAME", "archie"),
            user=os.getenv("DB_USER", "archie"),
            password=_get_db_password(),
        )

    def get_archie_emotional_state(self, user_id: int) -> str:
        """
        Get ARCHIE's current emotional state for a user.

        This integrates with the Consciousness system to make ARCHIE's
        voice match her current mood toward the user.

        Args:
            user_id: User ID to get emotional state for

        Returns:
            Emotion string for voice synthesis
        """
        try:
            conn = self._get_db()
            try:
                cur = conn.cursor(cursor_factory=RealDictCursor)

                cur.execute(
                    """
                    SELECT current_mood, mood_intensity, relationship_strength
                    FROM archie_emotional_state
                    WHERE user_id = %s
                    ORDER BY timestamp DESC
                    LIMIT 1
                """,
                    (user_id,),
                )

                state = cur.fetchone()

                if state:
                    return self._map_mood_to_emotion(
                        state["current_mood"],
                        float(state.get("mood_intensity", 0.5)),
                        float(state.get("relationship_strength", 0.5)),
                    )
                return "neutral"
            finally:
                try:
                    cur.close()
                except Exception:
                    pass
                try:
                    conn.close()
                except Exception:
                    pass

        except Exception as e:
            print(f"[VoiceDNA] Emotional state error: {e}")
            return "neutral"

    def _map_mood_to_emotion(self, mood: str, intensity: float, relationship: float) -> str:
        """
        Map ARCHIE's mood/intensity/relationship to voice emotion.

        High intensity amplifies emotional expression.
        Strong relationships favor warmer tones.
        """
        if not mood:
            return "neutral"

        mood = mood.lower()

        # Map moods to voice emotions based on intensity
        mood_map = {
            "happy": "excited" if intensity > 0.7 else "playful",
            "excited": "excited",
            "curious": "curious",
            "caring": "empathetic",
            "empathetic": "empathetic",
            "focused": "focused",
            "concerned": "concerned",
            "thoughtful": "thoughtful",
            "confident": "confident",
            "gentle": "gentle",
            "neutral": "neutral",
        }

        base_emotion = mood_map.get(mood, "neutral")

        # High relationship strength adds warmth
        if relationship > 0.7 and base_emotion in ["neutral", "focused"]:
            base_emotion = "gentle"

        return base_emotion

    def get_status(self) -> Dict[str, Any]:
        """Get voice synthesis system status"""
        kokoro_installed = KokoroEngine.check_available()
        kokoro_loaded = self._kokoro is not None and self._kokoro.is_loaded
        return {
            "tts_available": self.tts is not None or kokoro_installed,
            "model_loaded": self._model_loaded or kokoro_loaded,
            "engines": {
                "kokoro": {
                    "available": kokoro_installed,
                    "loaded": kokoro_loaded,
                    "voices": 28,
                },
                "xtts_v2": {
                    "available": self.tts is not None,
                    "loaded": self._model_loaded,
                    "voices": len(self._available_speakers) or 32,
                },
            },
            "default_engine": "kokoro",
            "speaker": (self._select_speaker() if self._available_speakers else self.DEFAULT_SPEAKER),
            "available_speakers": len(self._available_speakers),
            "supported_emotions": list(self.EMOTION_VOICE_MAP.keys()),
        }

    # ========================================
    # Phoneme-Based Word Caching System
    # ========================================

    def synthesize_word(
        self,
        word: str,
        emotion: str = "neutral",
        quality: str = "standard",
        language: str = "en",
    ) -> Optional[bytes]:
        """
        Synthesize a single word and return raw audio bytes.

        Args:
            word: Single word to synthesize
            emotion: Emotional tone
            quality: Quality preset ('standard' or 'high')
            language: Language code ('en', 'fr', etc.)

        Returns:
            Raw WAV audio bytes or None on failure
        """
        if not self._model_loaded:
            self._init_tts()

        if not self.tts or not word.strip():
            return None

        params = self.EMOTION_VOICE_MAP.get(emotion, self.EMOTION_VOICE_MAP["neutral"])
        speaker = self._select_speaker()
        quality_kwargs = self.QUALITY_PRESETS.get(quality, self.QUALITY_PRESETS["standard"])

        try:
            import tempfile

            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_file:
                temp_path = temp_file.name

            self.tts.tts_to_file(
                text=word,
                speaker=speaker,
                language=language,
                file_path=temp_path,
                speed=params["speed"],
                **quality_kwargs,
            )

            with open(temp_path, "rb") as f:
                audio_bytes = f.read()

            os.unlink(temp_path)
            return audio_bytes

        except Exception as e:
            print(f"[VoiceDNA] Word synthesis error for '{word}': {e}")
            return None

    def _check_word_cache(self, word: str, emotion: str) -> Optional[bytes]:
        """
        Check if a word is cached in voice_word_cache.

        Args:
            word: Word to look up
            emotion: Emotion context

        Returns:
            Raw audio bytes if cached, None otherwise
        """
        try:
            extractor = get_phoneme_extractor()
            word_hash = extractor.get_word_hash(word, emotion)

            conn = self._get_db()
            try:
                cur = conn.cursor()

                cur.execute(
                    """
                    UPDATE voice_word_cache
                    SET hit_count = COALESCE(hit_count, 0) + 1,
                        usage_count = COALESCE(usage_count, 0) + 1,
                        last_used = NOW()
                    WHERE text_hash = %s
                    RETURNING full_audio_cache
                """,
                    (word_hash,),
                )

                result = cur.fetchone()
                conn.commit()

                if result and result[0]:
                    cached = result[0]
                    if isinstance(cached, memoryview):
                        return bytes(cached)
                    return cached
                return None
            finally:
                try:
                    cur.close()
                except Exception:
                    pass
                try:
                    conn.close()
                except Exception:
                    pass

        except Exception as e:
            print(f"[VoiceDNA] Word cache check error: {e}")
            return None

    def _save_word_to_cache(
        self,
        word: str,
        phonemes: List[str],
        emotion: str,
        audio_bytes: bytes,
        duration_ms: int,
    ):
        """
        Save a synthesized word to the cache with its phoneme sequence.

        Args:
            word: The word text
            phonemes: List of IPA phonemes
            emotion: Emotion context
            audio_bytes: Raw WAV audio
            duration_ms: Generation time in milliseconds
        """
        try:
            extractor = get_phoneme_extractor()
            word_hash = extractor.get_word_hash(word, emotion)
            params = self.EMOTION_VOICE_MAP.get(emotion, self.EMOTION_VOICE_MAP["neutral"])

            conn = self._get_db()
            try:
                cur = conn.cursor()

                cur.execute(
                    """
                    INSERT INTO voice_word_cache
                    (word_text, phoneme_sequence, full_audio_cache, text_hash, emotion_context,
                     voice_parameters, duration_ms, hit_count, usage_count, last_used)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, 0, 0, NOW())
                    ON CONFLICT (text_hash) WHERE text_hash IS NOT NULL DO UPDATE
                    SET full_audio_cache = EXCLUDED.full_audio_cache,
                        phoneme_sequence = EXCLUDED.phoneme_sequence,
                        hit_count = COALESCE(voice_word_cache.hit_count, 0) + 1,
                        usage_count = COALESCE(voice_word_cache.usage_count, 0) + 1,
                        last_used = NOW()
                """,
                    (
                        word[:100],
                        json.dumps(phonemes),
                        audio_bytes,
                        word_hash,
                        emotion,
                        json.dumps(params),
                        duration_ms,
                    ),
                )

                conn.commit()
            finally:
                try:
                    cur.close()
                except Exception:
                    pass
                try:
                    conn.close()
                except Exception:
                    pass

        except Exception as e:
            print(f"[VoiceDNA] Word cache save error: {e}")

    def _save_phonemes_to_library(self, phonemes: List[str], emotion: str):
        """
        Record unique phonemes in the phoneme library for reference.

        Args:
            phonemes: List of IPA phonemes
            emotion: Emotion context
        """
        try:
            conn = self._get_db()
            try:
                cur = conn.cursor()

                for phoneme in phonemes:
                    if not phoneme or len(phoneme) > 10:
                        continue

                    cur.execute(
                        """
                        INSERT INTO voice_phoneme_library (phoneme_text, emotion_context)
                        VALUES (%s, %s)
                        ON CONFLICT (phoneme_text, emotion_context) DO NOTHING
                    """,
                        (phoneme, emotion),
                    )

                conn.commit()
            finally:
                try:
                    cur.close()
                except Exception:
                    pass
                try:
                    conn.close()
                except Exception:
                    pass

        except Exception as e:
            print(f"[VoiceDNA] Phoneme library save error: {e}")

    def synthesize_with_word_cache(
        self, text: str, emotion: str = "neutral", user_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Synthesize speech using word-level caching with phoneme metadata.

        This method:
        1. Extracts words and their phonemes from text
        2. Checks cache for each word
        3. Synthesizes only uncached words
        4. Concatenates word audio to form complete phrase

        Args:
            text: Text to synthesize
            emotion: Emotional tone
            user_id: User ID for logging

        Returns:
            Dict with success, audio_base64, cache_stats, etc.
        """
        if not self._model_loaded:
            self._init_tts()

        if not self.tts:
            return {"success": False, "error": "TTS not available"}

        if not text or not text.strip():
            return {"success": False, "error": "No text provided"}

        text = text.strip()
        if len(text) > 500:
            text = text[:500]

        start_time = time.time()
        extractor = get_phoneme_extractor()

        # Extract words with phonemes
        word_data = extractor.extract_phonemes(text)
        if not word_data:
            # Fallback to full phrase synthesis if phoneme extraction fails
            return self.synthesize(text, emotion, user_id)

        # Collect audio segments
        audio_segments = []
        cache_hits = 0
        cache_misses = 0
        words_synthesized = []

        for wd in word_data:
            word = wd["word"]
            phonemes = wd["phonemes"]

            # Skip punctuation - add pause instead
            if wd.get("is_punctuation") or not word.strip() or word in ".,!?;:":
                continue

            # Check word cache
            cached_audio = self._check_word_cache(word, emotion)

            if cached_audio:
                audio_segments.append(cached_audio)
                cache_hits += 1
            else:
                # Synthesize the word
                word_audio = self.synthesize_word(word, emotion)
                if word_audio:
                    audio_segments.append(word_audio)
                    cache_misses += 1

                    # Cache the word with phonemes
                    gen_time = int((time.time() - start_time) * 100)  # Approximate
                    self._save_word_to_cache(word, phonemes, emotion, word_audio, gen_time)

                    # Record phonemes in library
                    self._save_phonemes_to_library(phonemes, emotion)

                    words_synthesized.append(word)

        if not audio_segments:
            return {"success": False, "error": "No audio segments generated"}

        # Concatenate audio segments
        try:
            combined_audio = self._concatenate_wav_segments(audio_segments)
            audio_base64 = base64.b64encode(combined_audio).decode("utf-8")

            generation_time = int((time.time() - start_time) * 1000)

            # Log generation
            self._log_generation(
                user_id,
                len(text),
                emotion,
                cached=(cache_misses == 0),
                time_ms=generation_time,
            )

            return {
                "success": True,
                "audio_base64": audio_base64,
                "cached": cache_misses == 0,
                "emotion": emotion,
                "generation_time_ms": generation_time,
                "cache_stats": {
                    "hits": cache_hits,
                    "misses": cache_misses,
                    "words_synthesized": words_synthesized,
                },
                "method": "word_cache",
            }

        except Exception as e:
            print(f"[VoiceDNA] Audio concatenation error: {e}")
            # Fallback to full phrase synthesis
            return self.synthesize(text, emotion, user_id)

    def _concatenate_wav_segments(self, segments: List[bytes]) -> bytes:
        """
        Concatenate multiple WAV audio segments into one.

        Args:
            segments: List of WAV audio bytes

        Returns:
            Combined WAV audio bytes
        """
        import wave
        import struct
        import tempfile

        if not segments:
            raise ValueError("No segments to concatenate")

        if len(segments) == 1:
            return segments[0]

        # Use wave module to properly concatenate WAV files
        output = io.BytesIO()

        # Read first segment to get parameters
        first_segment = io.BytesIO(segments[0])
        with wave.open(first_segment, "rb") as first_wav:
            params = first_wav.getparams()
            all_frames = first_wav.readframes(first_wav.getnframes())

        # Read remaining segments
        for segment in segments[1:]:
            seg_io = io.BytesIO(segment)
            try:
                with wave.open(seg_io, "rb") as seg_wav:
                    # Add small silence gap between words (0.05 seconds)
                    gap_frames = int(params.framerate * 0.05) * params.nchannels * params.sampwidth
                    all_frames += b"\x00" * gap_frames
                    all_frames += seg_wav.readframes(seg_wav.getnframes())
            except Exception as e:
                print(f"[VoiceDNA] Error reading segment: {e}")
                continue

        # Write combined audio
        with wave.open(output, "wb") as out_wav:
            out_wav.setparams(params)
            out_wav.writeframes(all_frames)

        return output.getvalue()

    def cleanup_cache(self, max_age_days=30, min_hits=1):
        """Remove unused cache entries older than max_age_days with fewer than min_hits.

        Args:
            max_age_days: Only delete entries older than this many days
            min_hits: Only delete entries with hit_count below this threshold

        Returns:
            Number of deleted entries
        """
        try:
            conn = self._get_db()
            try:
                cur = conn.cursor()
                cur.execute(
                    """
                    DELETE FROM voice_word_cache
                    WHERE COALESCE(hit_count, 0) < %s
                    AND created_at < NOW() - INTERVAL '1 day' * %s
                    RETURNING id
                """,
                    (min_hits, max_age_days),
                )
                deleted = cur.rowcount
                conn.commit()
                return deleted
            finally:
                try:
                    cur.close()
                except Exception:
                    pass
                try:
                    conn.close()
                except Exception:
                    pass
        except Exception as e:
            print(f"[VoiceDNA] Cache cleanup error: {e}")
            return 0

    # ========================================
    # Voice Management API Methods
    # ========================================

    XTTS_SPEAKERS = [
        "Claribel Dervla",
        "Daisy Studious",
        "Gracie Wise",
        "Tammie Ema",
        "Alison Dietlinde",
        "Ana Florence",
        "Annmarie Nele",
        "Asya Anara",
        "Brenda Stern",
        "Gitta Nikolina",
        "Henriette Usha",
        "Sofia Hellen",
        "Tamaru Naoko",
        "Tanja Adelina",
        "Vjollca Johnnie",
        "Andrew Chipper",
        "Badr Odhiambo",
        "Dionisio Schuyler",
        "Royston Min",
        "Viktor Eka",
        "Abrahan Mack",
        "Adde Michal",
        "Baldur Sanjin",
        "Craig Gutsy",
        "Damien Black",
        "Gilberto Mathias",
        "Ilkin Urbano",
        "Kazuhiko Atallah",
        "Ludvig Milivoj",
        "Suad Qasim",
        "Torcull Diarmuid",
        "Viktor Menelaos",
    ]

    def get_available_speakers(self, engine: str = None):
        """
        Return available speakers, optionally filtered by engine.

        Args:
            engine: 'kokoro', 'xtts_v2', or None for both grouped
        """
        if engine == "kokoro":
            try:
                return self._get_kokoro().get_speakers()
            except ImportError:
                return []
        elif engine == "xtts_v2":
            if not self._model_loaded:
                self._init_tts()
            if self._available_speakers:
                return list(self._available_speakers)
            return list(self.XTTS_SPEAKERS)
        else:
            # Return both grouped
            try:
                kokoro_speakers = self._get_kokoro().get_speakers_grouped()
            except ImportError:
                kokoro_speakers = {}
            return {"kokoro": kokoro_speakers, "xtts_v2": self.XTTS_SPEAKERS}

    def synthesize_with_params(
        self,
        text: str,
        speaker: str = "Ana Florence",
        speed: float = 1.0,
        pitch_shift: float = 1.0,
        warmth: float = 0.8,
        emotion: str = "neutral",
        quality: str = "standard",
        engine: str = "kokoro",
        voice_blend: str = None,
        language: str = "en",
    ) -> Dict[str, Any]:
        """
        Generate speech with explicit parameters for preview. No caching.

        Args:
            text: Text to synthesize (max 500 chars)
            speaker: Speaker name
            speed: Speed multiplier (0.50-2.00)
            pitch_shift: Pitch shift (0.80-1.20) — XTTS only
            warmth: Warmth parameter (0.00-1.00) — XTTS only
            emotion: Emotion label (for metadata only)
            quality: Quality preset ('standard' or 'high')
            engine: TTS engine ('kokoro' or 'xtts_v2')
            voice_blend: Kokoro voice blend string (e.g. 'af_bella:60,am_adam:40')
            language: Language code ('en', 'fr', etc.)

        Returns:
            Dict with success, audio_base64, generation_time_ms, parameters_used
        """
        if not text or not text.strip():
            return {"success": False, "error": "No text provided"}

        text = text.strip()[:500]
        speed = max(0.50, min(2.00, speed))

        # Kokoro is English-only; auto-route non-English to XTTS v2
        if language != "en" and engine == "kokoro":
            engine = "xtts_v2"

        start_time = time.time()

        try:
            if engine == "kokoro":
                kokoro = self._get_kokoro()
                audio_bytes = kokoro.synthesize_to_wav(text, voice=speaker, speed=speed, voice_blend=voice_blend)
                audio_base64 = base64.b64encode(audio_bytes).decode("utf-8")
            else:
                # XTTS v2 path
                if not self._model_loaded:
                    self._init_tts()
                if not self.tts:
                    return {"success": False, "error": "TTS not available"}

                pitch_shift = max(0.80, min(1.20, pitch_shift))
                warmth = max(0.00, min(1.00, warmth))

                available = self.get_available_speakers(engine="xtts_v2")
                if speaker not in available:
                    speaker = self.DEFAULT_SPEAKER

                import tempfile

                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_file:
                    temp_path = temp_file.name

                quality_kwargs = self.QUALITY_PRESETS.get(quality, self.QUALITY_PRESETS["standard"])
                self.tts.tts_to_file(
                    text=text,
                    speaker=speaker,
                    language=language,
                    file_path=temp_path,
                    speed=speed,
                    **quality_kwargs,
                )

                with open(temp_path, "rb") as f:
                    audio_bytes = f.read()
                os.unlink(temp_path)
                audio_base64 = base64.b64encode(audio_bytes).decode("utf-8")

            generation_time = int((time.time() - start_time) * 1000)

            return {
                "success": True,
                "audio_base64": audio_base64,
                "generation_time_ms": generation_time,
                "parameters_used": {
                    "speaker": speaker,
                    "speed": speed,
                    "pitch_shift": pitch_shift,
                    "warmth": warmth,
                    "emotion": emotion,
                    "quality": quality,
                    "engine": engine,
                    "voice_blend": voice_blend,
                    "language": language,
                },
            }

        except Exception as e:
            print(f"[VoiceDNA] Preview synthesis error ({engine}): {e}")
            return {"success": False, "error": str(e)}

    def synthesize_for_agent(
        self,
        text: str,
        agent_id: int,
        emotion: str = "neutral",
        user_id: Optional[int] = None,
        quality: str = "standard",
        language: str = None,
    ) -> Dict[str, Any]:
        """
        Synthesize speech using an agent's voice profile.
        Falls back to defaults if no profile exists.
        Language from profile is used if not explicitly passed.
        """
        # Load agent's voice profile
        profile = self._get_agent_profile(agent_id)

        if profile:
            speaker = profile.get("speaker", self.DEFAULT_SPEAKER)
            engine = profile.get("engine", "kokoro")
            voice_blend = profile.get("voice_blend")
            # Use profile language if not explicitly passed
            if language is None:
                language = profile.get("language", "en")
            base_params = {
                "speed": float(profile.get("speed", 1.0)),
                "pitch_shift": float(profile.get("pitch_shift", 1.0)),
                "warmth": float(profile.get("warmth", 0.8)),
            }
            overrides = profile.get("emotion_overrides", {})
            if emotion in overrides:
                base_params.update(overrides[emotion])

            default_emotion = profile.get("default_emotion", "neutral")
            if emotion == "neutral" and default_emotion != "neutral":
                emotion = default_emotion
        else:
            speaker = self.DEFAULT_SPEAKER
            engine = "kokoro"
            voice_blend = None
            if language is None:
                language = "en"
            base_params = self.EMOTION_VOICE_MAP.get(emotion, self.EMOTION_VOICE_MAP["neutral"])

        # Kokoro is English-only; auto-route non-English to XTTS v2
        if language != "en" and engine == "kokoro":
            engine = "xtts_v2"

        if not text or not text.strip():
            return {"success": False, "error": "No text provided"}

        text = normalize_text_for_tts(text.strip())
        if len(text) > 500:
            text = text[:500]

        # Check agent-specific cache (engine+language-scoped)
        cache_key = self._get_agent_cache_key(text, emotion, agent_id, engine=engine, language=language)
        cached_audio = self._check_agent_cache(cache_key, agent_id)
        if cached_audio:
            self._log_generation(
                user_id,
                len(text),
                emotion,
                cached=True,
                time_ms=0,
                engine=engine,
                language=language,
            )
            return {
                "success": True,
                "audio_base64": cached_audio,
                "cached": True,
                "emotion": emotion,
                "agent_id": agent_id,
            }

        start_time = time.time()

        try:
            if engine == "kokoro":
                kokoro = self._get_kokoro()
                audio_bytes = kokoro.synthesize_to_wav(
                    text,
                    voice=speaker,
                    speed=base_params.get("speed", 1.0),
                    voice_blend=voice_blend,
                )
                audio_base64 = base64.b64encode(audio_bytes).decode("utf-8")
            else:
                if not self._model_loaded:
                    self._init_tts()
                if not self.tts:
                    return {"success": False, "error": "TTS not available"}

                import tempfile

                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_file:
                    temp_path = temp_file.name

                quality_kwargs = self.QUALITY_PRESETS.get(quality, self.QUALITY_PRESETS["standard"])
                self.tts.tts_to_file(
                    text=text,
                    speaker=speaker,
                    language=language,
                    file_path=temp_path,
                    speed=base_params.get("speed", 1.0),
                    **quality_kwargs,
                )

                with open(temp_path, "rb") as f:
                    audio_bytes = f.read()
                os.unlink(temp_path)
                audio_base64 = base64.b64encode(audio_bytes).decode("utf-8")

            generation_time = int((time.time() - start_time) * 1000)

            self._save_agent_cache(
                cache_key,
                text,
                emotion,
                audio_base64,
                base_params,
                generation_time,
                agent_id,
                engine=engine,
                language=language,
            )
            self._log_generation(
                user_id,
                len(text),
                emotion,
                cached=False,
                time_ms=generation_time,
                engine=engine,
                language=language,
            )

            return {
                "success": True,
                "audio_base64": audio_base64,
                "cached": False,
                "emotion": emotion,
                "agent_id": agent_id,
                "speaker": speaker,
                "engine": engine,
                "generation_time_ms": generation_time,
                "parameters": base_params,
            }

        except Exception as e:
            print(f"[VoiceDNA] Agent synthesis error ({engine}): {e}")
            return {"success": False, "error": str(e)}

    def synthesize_for_agent_chunked(
        self,
        text: str,
        agent_id: int,
        emotion: str = "neutral",
        user_id: Optional[int] = None,
        quality: str = "standard",
        language: str = None,
    ) -> Dict[str, Any]:
        """
        Synthesize long text by splitting into sentence-boundary chunks.
        Each chunk is synthesized and cached individually via synthesize_for_agent().

        Accepts up to 2000 chars. Returns array of audio chunks for sequential playback.
        """
        if not text or not text.strip():
            return {"success": False, "error": "No text provided"}

        text = normalize_text_for_tts(text.strip())
        if len(text) > 2000:
            text = text[:2000]

        # Split into sentence-boundary chunks (each <= 500 chars)
        chunks = split_into_sentences(text, max_chunk=500)

        results = []
        for i, chunk_text in enumerate(chunks):
            result = self.synthesize_for_agent(
                text=chunk_text,
                agent_id=agent_id,
                emotion=emotion,
                user_id=user_id,
                quality=quality,
                language=language,
            )
            if result.get("success"):
                results.append(
                    {
                        "audio_base64": result["audio_base64"],
                        "cached": result.get("cached", False),
                        "chunk_index": i,
                        "chunk_text": chunk_text[:80],
                    }
                )
            else:
                print(f"[VoiceDNA] Chunk {i} failed: {result.get('error')}")

        if not results:
            return {"success": False, "error": "All chunks failed to synthesize"}

        return {
            "success": True,
            "chunks": results,
            "total_chunks": len(chunks),
            "synthesized_chunks": len(results),
        }

    def _get_agent_profile(self, agent_id: int) -> Optional[Dict[str, Any]]:
        """Load agent's voice profile from DB"""
        try:
            conn = self._get_db()
            try:
                cur = conn.cursor(cursor_factory=RealDictCursor)
                cur.execute(
                    """
                    SELECT speaker, speed, pitch_shift, warmth, default_emotion,
                           emotion_overrides, engine, voice_blend, language
                    FROM agent_voice_profiles
                    WHERE agent_id = %s AND is_active = TRUE
                """,
                    (agent_id,),
                )
                result = cur.fetchone()
                return dict(result) if result else None
            finally:
                try:
                    cur.close()
                except Exception:
                    pass
                try:
                    conn.close()
                except Exception:
                    pass
        except Exception as e:
            print(f"[VoiceDNA] Profile load error: {e}")
            return None

    def _get_agent_cache_key(
        self,
        text: str,
        emotion: str,
        agent_id: int,
        engine: str = "kokoro",
        language: str = "en",
    ) -> str:
        """Generate cache key scoped to agent, engine, and language.
        Text is lowercased to match _get_cache_key behavior and maximize cache hits."""
        normalized = text.lower().strip()
        content = f"{engine}|{language}|agent:{agent_id}|{normalized}|{emotion}"
        return hashlib.sha256(content.encode()).hexdigest()[:32]

    def _check_agent_cache(self, cache_key: str, agent_id: int) -> Optional[str]:
        """Check voice cache for agent-specific audio"""
        try:
            conn = self._get_db()
            try:
                cur = conn.cursor()
                cur.execute(
                    """
                    UPDATE voice_word_cache
                    SET hit_count = COALESCE(hit_count, 0) + 1,
                        usage_count = COALESCE(usage_count, 0) + 1,
                        last_used = NOW()
                    WHERE text_hash = %s AND (agent_id = %s OR agent_id IS NULL)
                    RETURNING full_audio_cache
                """,
                    (cache_key, agent_id),
                )
                result = cur.fetchone()
                conn.commit()

                if result and result[0]:
                    cached = result[0]
                    if isinstance(cached, (bytes, memoryview)):
                        return cached.decode("utf-8") if isinstance(cached, bytes) else bytes(cached).decode("utf-8")
                    return cached
                return None
            finally:
                try:
                    cur.close()
                except Exception:
                    pass
                try:
                    conn.close()
                except Exception:
                    pass
        except Exception as e:
            print(f"[VoiceDNA] Agent cache check error: {e}")
            return None

    def _save_agent_cache(
        self,
        cache_key: str,
        text: str,
        emotion: str,
        audio_base64: str,
        params: dict,
        duration_ms: int,
        agent_id: int,
        engine: str = "kokoro",
        language: str = "en",
    ):
        """Save audio to cache with agent_id, engine, and language"""
        try:
            conn = self._get_db()
            try:
                cur = conn.cursor()
                cur.execute(
                    """
                    INSERT INTO voice_word_cache
                    (word_text, phoneme_sequence, full_audio_cache, text_hash, emotion_context,
                     voice_parameters, duration_ms, hit_count, usage_count, last_used, agent_id, engine, language)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, 0, 0, NOW(), %s, %s, %s)
                    ON CONFLICT (text_hash) WHERE text_hash IS NOT NULL DO UPDATE
                    SET full_audio_cache = CASE WHEN voice_word_cache.is_locked THEN voice_word_cache.full_audio_cache ELSE EXCLUDED.full_audio_cache END,
                        hit_count = COALESCE(voice_word_cache.hit_count, 0) + 1,
                        usage_count = COALESCE(voice_word_cache.usage_count, 0) + 1,
                        last_used = NOW(),
                        voice_parameters = CASE WHEN voice_word_cache.is_locked THEN voice_word_cache.voice_parameters ELSE EXCLUDED.voice_parameters END,
                        agent_id = CASE WHEN voice_word_cache.is_locked THEN voice_word_cache.agent_id ELSE EXCLUDED.agent_id END,
                        engine = CASE WHEN voice_word_cache.is_locked THEN voice_word_cache.engine ELSE EXCLUDED.engine END,
                        language = CASE WHEN voice_word_cache.is_locked THEN voice_word_cache.language ELSE EXCLUDED.language END
                """,
                    (
                        text[:100],
                        json.dumps([]),
                        audio_base64.encode("utf-8"),
                        cache_key,
                        emotion,
                        json.dumps(params),
                        duration_ms,
                        agent_id,
                        engine,
                        language,
                    ),
                )
                conn.commit()
            finally:
                try:
                    cur.close()
                except Exception:
                    pass
                try:
                    conn.close()
                except Exception:
                    pass
        except Exception as e:
            print(f"[VoiceDNA] Agent cache save error: {e}")


# Singleton instance with lazy loading
_synthesizer = None


def get_voice_synthesizer() -> VoiceSynthesizer:
    """Get or create voice synthesizer singleton"""
    global _synthesizer
    if _synthesizer is None:
        _synthesizer = VoiceSynthesizer(lazy_init=True)
    return _synthesizer


# Test function
def test_voice_synthesis():
    """Test voice synthesis functionality"""
    synthesizer = get_voice_synthesizer()

    print("Voice Synthesis Status:")
    print(synthesizer.get_status())

    print("\nTesting synthesis...")
    result = synthesizer.synthesize(
        "Hello! I'm A.R.C.H.I.E., your autonomous resource and coordination hub. How can I help you today?",
        emotion="friendly",
    )

    if result["success"]:
        print(f"Success! Audio length: {len(result.get('audio_base64', ''))} chars")
        print(f"Cached: {result.get('cached', False)}")
        print(f"Generation time: {result.get('generation_time_ms', 0)}ms")
    else:
        print(f"Failed: {result.get('error')}")


if __name__ == "__main__":
    test_voice_synthesis()

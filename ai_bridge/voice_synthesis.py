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
import io
import base64
import hashlib
import time
import json
import re
from typing import Optional, Dict, Any, List, Tuple
import psycopg2
from psycopg2.extras import RealDictCursor


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

    def extract_phonemes(self, text: str, lang: str = 'en-us') -> List[Dict[str, Any]]:
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
                    words.append({
                        'word': word.text,
                        'phonemes': phonemes,
                        'ipa': ''.join(phonemes),
                        'is_punctuation': word.is_punctuation if hasattr(word, 'is_punctuation') else False
                    })
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
            while word and word[0] in '.,!?;:"\'-(':
                tokens.append(word[0])
                word = word[1:]
            # Separate trailing punctuation
            trailing = []
            while word and word[-1] in '.,!?;:"\'-()':
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


class VoiceSynthesizer:
    """Voice synthesis with emotion modulation for A.R.C.H.I.E."""

    # Built-in XTTS v2 speakers - Ana Florence is warm, professional feminine
    DEFAULT_SPEAKER = "Ana Florence"

    # Fallback if Ana Florence not available
    FALLBACK_SPEAKERS = ["Annmarie Nele", "Suad Qasim", "Tammie Ema"]

    # Emotion-to-voice parameter mapping
    # speed: 0.5-2.0 (1.0 = normal)
    # pitch_shift: 0.8-1.2 (1.0 = no shift)
    # warmth: 0.0-1.0 (affects tone)
    EMOTION_VOICE_MAP = {
        'excited':    {'speed': 1.10, 'pitch_shift': 1.05, 'warmth': 0.90},
        'curious':    {'speed': 1.00, 'pitch_shift': 1.02, 'warmth': 0.85},
        'empathetic': {'speed': 0.90, 'pitch_shift': 0.98, 'warmth': 0.95},
        'focused':    {'speed': 0.95, 'pitch_shift': 1.00, 'warmth': 0.75},
        'playful':    {'speed': 1.05, 'pitch_shift': 1.03, 'warmth': 0.88},
        'concerned':  {'speed': 0.88, 'pitch_shift': 0.97, 'warmth': 0.92},
        'thoughtful': {'speed': 0.92, 'pitch_shift': 0.99, 'warmth': 0.82},
        'confident':  {'speed': 1.02, 'pitch_shift': 1.01, 'warmth': 0.80},
        'gentle':     {'speed': 0.88, 'pitch_shift': 0.98, 'warmth': 0.95},
        'neutral':    {'speed': 1.00, 'pitch_shift': 1.00, 'warmth': 0.80},
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

        if not lazy_init:
            self._init_tts()

    def _init_tts(self):
        """Initialize Coqui TTS with XTTS v2 model"""
        if self._model_loaded:
            return

        try:
            # Auto-accept Coqui license (CPML for non-commercial use)
            os.environ['COQUI_TOS_AGREED'] = '1'

            from TTS.api import TTS

            print("[VoiceDNA] Initializing Coqui TTS with XTTS v2...")

            # XTTS v2 supports multiple speakers and languages
            # First run downloads ~1.5GB model
            self.tts = TTS("tts_models/multilingual/multi-dataset/xtts_v2")

            # Use CPU for stability (GPU optional but faster)
            device = os.getenv('TTS_DEVICE', 'cpu')
            self.tts.to(device)

            # Get available speakers
            if hasattr(self.tts, 'speakers'):
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

    def synthesize(self, text: str, emotion: str = 'neutral',
                   user_id: Optional[int] = None) -> Dict[str, Any]:
        """
        Generate speech from text with emotion modulation.

        Args:
            text: Text to synthesize (max 500 chars)
            emotion: Emotional tone ('excited', 'curious', 'empathetic', etc.)
            user_id: User ID for logging and personalization

        Returns:
            Dict with success, audio_base64, cached, emotion, parameters
        """
        # Lazy load TTS on first use
        if not self._model_loaded:
            self._init_tts()

        if not self.tts:
            return {
                'success': False,
                'error': 'TTS not available. Install with: pip install TTS>=0.22.0'
            }

        # Validate input
        if not text or not text.strip():
            return {'success': False, 'error': 'No text provided'}

        text = text.strip()
        if len(text) > 500:
            text = text[:500]  # Truncate to max length

        # Check cache first
        cache_key = self._get_cache_key(text, emotion)
        cached_audio = self._check_cache(cache_key)
        if cached_audio:
            self._log_generation(user_id, len(text), emotion, cached=True, time_ms=0)
            return {
                'success': True,
                'audio_base64': cached_audio,
                'cached': True,
                'emotion': emotion
            }

        # Get voice parameters for emotion
        params = self.EMOTION_VOICE_MAP.get(emotion, self.EMOTION_VOICE_MAP['neutral'])

        # Select speaker
        speaker = self._select_speaker()

        start_time = time.time()

        try:
            # Generate audio with XTTS v2
            # Note: tts_to_file expects a file path, so we use a temp file
            import tempfile

            with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as temp_file:
                temp_path = temp_file.name

            self.tts.tts_to_file(
                text=text,
                speaker=speaker,
                language="en",
                file_path=temp_path,
                speed=params['speed']
            )

            # Read generated audio
            with open(temp_path, 'rb') as f:
                audio_bytes = f.read()

            # Clean up temp file
            os.unlink(temp_path)

            # Encode to base64 for web playback
            audio_base64 = base64.b64encode(audio_bytes).decode('utf-8')

            generation_time = int((time.time() - start_time) * 1000)

            # Cache the result
            self._save_to_cache(cache_key, text, emotion, audio_base64, params, generation_time)

            # Log generation
            self._log_generation(user_id, len(text), emotion, cached=False, time_ms=generation_time)

            return {
                'success': True,
                'audio_base64': audio_base64,
                'cached': False,
                'emotion': emotion,
                'parameters': params,
                'speaker': speaker,
                'generation_time_ms': generation_time
            }

        except Exception as e:
            print(f"[VoiceDNA] Synthesis error: {e}")
            return {'success': False, 'error': str(e)}

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

    def _get_cache_key(self, text: str, emotion: str) -> str:
        """Generate cache key from text and emotion"""
        speaker = self._select_speaker()
        content = f"{text}|{emotion}|{speaker}"
        return hashlib.sha256(content.encode()).hexdigest()[:32]

    def _check_cache(self, cache_key: str) -> Optional[str]:
        """Check voice_word_cache for existing audio"""
        try:
            conn = self._get_db()
            cur = conn.cursor()

            # Update hit count and return audio if exists
            # Using correct column names: full_audio_cache, usage_count, last_used
            cur.execute("""
                UPDATE voice_word_cache
                SET hit_count = COALESCE(hit_count, 0) + 1,
                    usage_count = COALESCE(usage_count, 0) + 1,
                    last_used = NOW()
                WHERE text_hash = %s
                RETURNING full_audio_cache
            """, (cache_key,))

            result = cur.fetchone()
            conn.commit()
            cur.close()
            conn.close()

            # full_audio_cache is bytea, need to decode if it's base64 stored as text
            if result and result[0]:
                cached = result[0]
                # If it's bytes (bytea), decode to string
                if isinstance(cached, (bytes, memoryview)):
                    return cached.decode('utf-8') if isinstance(cached, bytes) else bytes(cached).decode('utf-8')
                return cached
            return None

        except Exception as e:
            print(f"[VoiceDNA] Cache check error: {e}")
            return None

    def _save_to_cache(self, cache_key: str, text: str, emotion: str,
                       audio_base64: str, params: dict, duration_ms: int):
        """Save generated audio to cache"""
        try:
            conn = self._get_db()
            cur = conn.cursor()

            # Using correct column names: word_text, phoneme_sequence, full_audio_cache
            cur.execute("""
                INSERT INTO voice_word_cache
                (word_text, phoneme_sequence, full_audio_cache, text_hash, emotion_context, voice_parameters, duration_ms, hit_count, usage_count, last_used)
                VALUES (%s, %s, %s, %s, %s, %s, %s, 0, 0, NOW())
                ON CONFLICT (text_hash) WHERE text_hash IS NOT NULL DO UPDATE
                SET full_audio_cache = EXCLUDED.full_audio_cache,
                    hit_count = COALESCE(voice_word_cache.hit_count, 0) + 1,
                    usage_count = COALESCE(voice_word_cache.usage_count, 0) + 1,
                    last_used = NOW(),
                    emotion_context = EXCLUDED.emotion_context,
                    voice_parameters = EXCLUDED.voice_parameters
            """, (
                text[:100],  # Truncate for word_text column
                json.dumps([]),  # phoneme_sequence as empty JSON array
                audio_base64.encode('utf-8'),  # Store as bytes
                cache_key,
                emotion,
                json.dumps(params),
                duration_ms
            ))

            conn.commit()
            cur.close()
            conn.close()

        except Exception as e:
            print(f"[VoiceDNA] Cache save error: {e}")

    def _log_generation(self, user_id: Optional[int], text_length: int,
                        emotion: str, cached: bool, time_ms: int):
        """Log voice generation for analytics"""
        try:
            conn = self._get_db()
            cur = conn.cursor()

            cur.execute("""
                INSERT INTO voice_generation_log
                (user_id, text_length, emotion, cached, generation_time_ms)
                VALUES (%s, %s, %s, %s, %s)
            """, (user_id, text_length, emotion, cached, time_ms))

            conn.commit()
            cur.close()
            conn.close()

        except Exception as e:
            # Don't fail on logging errors
            print(f"[VoiceDNA] Log error: {e}")

    def _get_db(self):
        """Get database connection"""
        return psycopg2.connect(
            host=os.getenv('DB_HOST', 'archie_database'),
            port=os.getenv('DB_PORT', '5432'),
            database=os.getenv('DB_NAME', 'archie'),
            user=os.getenv('DB_USER', 'archie'),
            password=os.getenv('DB_PASSWORD', '')
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
            cur = conn.cursor(cursor_factory=RealDictCursor)

            cur.execute("""
                SELECT current_mood, mood_intensity, relationship_strength
                FROM archie_emotional_state
                WHERE user_id = %s
                ORDER BY timestamp DESC
                LIMIT 1
            """, (user_id,))

            state = cur.fetchone()
            cur.close()
            conn.close()

            if state:
                return self._map_mood_to_emotion(
                    state['current_mood'],
                    float(state.get('mood_intensity', 0.5)),
                    float(state.get('relationship_strength', 0.5))
                )
            return 'neutral'

        except Exception as e:
            print(f"[VoiceDNA] Emotional state error: {e}")
            return 'neutral'

    def _map_mood_to_emotion(self, mood: str, intensity: float,
                             relationship: float) -> str:
        """
        Map ARCHIE's mood/intensity/relationship to voice emotion.

        High intensity amplifies emotional expression.
        Strong relationships favor warmer tones.
        """
        if not mood:
            return 'neutral'

        mood = mood.lower()

        # Map moods to voice emotions based on intensity
        mood_map = {
            'happy': 'excited' if intensity > 0.7 else 'playful',
            'excited': 'excited',
            'curious': 'curious',
            'caring': 'empathetic',
            'empathetic': 'empathetic',
            'focused': 'focused',
            'concerned': 'concerned',
            'thoughtful': 'thoughtful',
            'confident': 'confident',
            'gentle': 'gentle',
            'neutral': 'neutral',
        }

        base_emotion = mood_map.get(mood, 'neutral')

        # High relationship strength adds warmth
        if relationship > 0.7 and base_emotion in ['neutral', 'focused']:
            base_emotion = 'gentle'

        return base_emotion

    def get_status(self) -> Dict[str, Any]:
        """Get voice synthesis system status"""
        return {
            'tts_available': self.tts is not None,
            'model_loaded': self._model_loaded,
            'engine': 'Coqui TTS (XTTS v2)' if self.tts else 'Not initialized',
            'speaker': self._select_speaker() if self._available_speakers else self.DEFAULT_SPEAKER,
            'available_speakers': len(self._available_speakers),
            'supported_emotions': list(self.EMOTION_VOICE_MAP.keys())
        }

    # ========================================
    # Phoneme-Based Word Caching System
    # ========================================

    def synthesize_word(self, word: str, emotion: str = 'neutral') -> Optional[bytes]:
        """
        Synthesize a single word and return raw audio bytes.

        Args:
            word: Single word to synthesize
            emotion: Emotional tone

        Returns:
            Raw WAV audio bytes or None on failure
        """
        if not self._model_loaded:
            self._init_tts()

        if not self.tts or not word.strip():
            return None

        params = self.EMOTION_VOICE_MAP.get(emotion, self.EMOTION_VOICE_MAP['neutral'])
        speaker = self._select_speaker()

        try:
            import tempfile

            with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as temp_file:
                temp_path = temp_file.name

            self.tts.tts_to_file(
                text=word,
                speaker=speaker,
                language="en",
                file_path=temp_path,
                speed=params['speed']
            )

            with open(temp_path, 'rb') as f:
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
            cur = conn.cursor()

            cur.execute("""
                UPDATE voice_word_cache
                SET hit_count = COALESCE(hit_count, 0) + 1,
                    usage_count = COALESCE(usage_count, 0) + 1,
                    last_used = NOW()
                WHERE text_hash = %s
                RETURNING full_audio_cache
            """, (word_hash,))

            result = cur.fetchone()
            conn.commit()
            cur.close()
            conn.close()

            if result and result[0]:
                cached = result[0]
                if isinstance(cached, memoryview):
                    return bytes(cached)
                return cached
            return None

        except Exception as e:
            print(f"[VoiceDNA] Word cache check error: {e}")
            return None

    def _save_word_to_cache(self, word: str, phonemes: List[str], emotion: str,
                            audio_bytes: bytes, duration_ms: int):
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
            params = self.EMOTION_VOICE_MAP.get(emotion, self.EMOTION_VOICE_MAP['neutral'])

            conn = self._get_db()
            cur = conn.cursor()

            cur.execute("""
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
            """, (
                word[:100],
                json.dumps(phonemes),
                audio_bytes,
                word_hash,
                emotion,
                json.dumps(params),
                duration_ms
            ))

            conn.commit()
            cur.close()
            conn.close()

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
            cur = conn.cursor()

            for phoneme in phonemes:
                if not phoneme or len(phoneme) > 10:
                    continue

                cur.execute("""
                    INSERT INTO voice_phoneme_library (phoneme_text, emotion_context)
                    VALUES (%s, %s)
                    ON CONFLICT (phoneme_text, emotion_context) DO NOTHING
                """, (phoneme, emotion))

            conn.commit()
            cur.close()
            conn.close()

        except Exception as e:
            print(f"[VoiceDNA] Phoneme library save error: {e}")

    def synthesize_with_word_cache(self, text: str, emotion: str = 'neutral',
                                   user_id: Optional[int] = None) -> Dict[str, Any]:
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
            return {
                'success': False,
                'error': 'TTS not available'
            }

        if not text or not text.strip():
            return {'success': False, 'error': 'No text provided'}

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
            word = wd['word']
            phonemes = wd['phonemes']

            # Skip punctuation - add pause instead
            if wd.get('is_punctuation') or not word.strip() or word in '.,!?;:':
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
            return {'success': False, 'error': 'No audio segments generated'}

        # Concatenate audio segments
        try:
            combined_audio = self._concatenate_wav_segments(audio_segments)
            audio_base64 = base64.b64encode(combined_audio).decode('utf-8')

            generation_time = int((time.time() - start_time) * 1000)

            # Log generation
            self._log_generation(user_id, len(text), emotion,
                               cached=(cache_misses == 0), time_ms=generation_time)

            return {
                'success': True,
                'audio_base64': audio_base64,
                'cached': cache_misses == 0,
                'emotion': emotion,
                'generation_time_ms': generation_time,
                'cache_stats': {
                    'hits': cache_hits,
                    'misses': cache_misses,
                    'words_synthesized': words_synthesized
                },
                'method': 'word_cache'
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
        with wave.open(first_segment, 'rb') as first_wav:
            params = first_wav.getparams()
            all_frames = first_wav.readframes(first_wav.getnframes())

        # Read remaining segments
        for segment in segments[1:]:
            seg_io = io.BytesIO(segment)
            try:
                with wave.open(seg_io, 'rb') as seg_wav:
                    # Add small silence gap between words (0.05 seconds)
                    gap_frames = int(params.framerate * 0.05) * params.nchannels * params.sampwidth
                    all_frames += b'\x00' * gap_frames
                    all_frames += seg_wav.readframes(seg_wav.getnframes())
            except Exception as e:
                print(f"[VoiceDNA] Error reading segment: {e}")
                continue

        # Write combined audio
        with wave.open(output, 'wb') as out_wav:
            out_wav.setparams(params)
            out_wav.writeframes(all_frames)

        return output.getvalue()


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
        emotion='friendly'
    )

    if result['success']:
        print(f"Success! Audio length: {len(result.get('audio_base64', ''))} chars")
        print(f"Cached: {result.get('cached', False)}")
        print(f"Generation time: {result.get('generation_time_ms', 0)}ms")
    else:
        print(f"Failed: {result.get('error')}")


if __name__ == '__main__':
    test_voice_synthesis()

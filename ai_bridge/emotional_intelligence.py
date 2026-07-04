"""
A.R.C.H.I.E. Emotional Intelligence System
Learns from how people interact, builds trust, and develops personality

Hybrid approach: fast regex for real-time use + LLM classifier for deeper analysis.
LLM model: qwen25-classify (CPU-only, ~1.5B params, <500ms latency)
"""

import os
import re
import json
import logging
from typing import Dict, List, Tuple, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

LLM_SENTIMENT_ENABLED = os.getenv("LLM_SENTIMENT_ENABLED", "true").lower() == "true"

# Sentiment indicators
POSITIVE_INDICATORS = [
    "great",
    "excellent",
    "perfect",
    "awesome",
    "wonderful",
    "fantastic",
    "thank you",
    "thanks",
    "appreciate",
    "helpful",
    "love",
    "good job",
    "well done",
    "nice",
    "brilliant",
    "amazing",
    "impressive",
    "yes",
    "correct",
    "exactly",
    "right",
    "!",
    "please",
    "good",
    "better",
]

NEGATIVE_INDICATORS = [
    "wrong",
    "incorrect",
    "bad",
    "terrible",
    "awful",
    "useless",
    "broken",
    "error",
    "fail",
    "failed",
    "not working",
    "doesn't work",
    "bug",
    "issue",
    "problem",
    "frustrat",
    "confus",
    "unclear",
    "no",
    "stop",
    "hate",
    "worse",
    "disappointing",
]

UNCERTAINTY_INDICATORS = [
    "not sure",
    "maybe",
    "perhaps",
    "might",
    "could be",
    "unsure",
    "don't know",
    "unclear",
    "confused",
    "check",
    "verify",
    "confirm",
    "are you sure",
    "double check",
    "is this right",
]

CURIOSITY_INDICATORS = [
    "how",
    "why",
    "what",
    "when",
    "where",
    "explain",
    "tell me",
    "show me",
    "can you",
    "could you",
    "would you",
    "i want to learn",
    "teach me",
    "help me understand",
    "interested",
    "curious",
]

TRUST_BUILDING = [
    "trust",
    "reliable",
    "depend",
    "count on",
    "believe",
    "confidence",
    "consistent",
    "accurate",
    "precise",
]

ENCOURAGEMENT = [
    "keep going",
    "continue",
    "more",
    "tell me more",
    "keep learning",
    "good work",
    "you're doing well",
    "improving",
    "progress",
]

CRITICISM = [
    "wrong again",
    "still wrong",
    "you don't understand",
    "incorrect again",
    "not listening",
    "you're not",
    "you can't",
    "you don't",
]


def _llm_classify_sentiment(text: str) -> Optional[Dict[str, any]]:
    """
    Use qwen25-classify LLM for nuanced sentiment analysis.
    Returns structured result or None on failure (falls back to regex).
    """
    if not LLM_SENTIMENT_ENABLED:
        return None

    try:
        from tools.department_hq.services.department_dispatcher import get_dispatcher

        prompt = (
            "Analyze the emotional sentiment of this text. "
            "Respond ONLY with valid JSON, no other text.\n\n"
            "Text: " + text[:500] + "\n\n"
            "JSON format:\n"
            '{"sentiment":"positive|negative|neutral|mixed",'
            '"confidence":0.0-1.0,'
            '"tone":"enthusiastic|frustrated|curious|uncertain|sarcastic|grateful|neutral",'
            '"emotion":"excited|angry|sad|happy|confused|calm|anxious|hopeful",'
            '"signals":["list","of","detected","signals"]}'
        )

        dispatcher = get_dispatcher()
        dispatch_result = dispatcher.request_work(
            "classify",
            prompt,
            "emotional_intelligence",
            json_mode=True,
            timeout=10,
            prefer_agent="I.R.I.S.",
        )

        if not dispatch_result.success:
            return None

        result = json.loads(dispatch_result.response)

        # Validate required fields
        sentiment = result.get("sentiment", "neutral")
        if sentiment not in ("positive", "negative", "neutral", "mixed"):
            sentiment = "neutral"

        confidence = float(result.get("confidence", 0.5))
        confidence = max(0.0, min(1.0, confidence))

        tone = result.get("tone", "neutral")
        emotion = result.get("emotion", "calm")
        signals = result.get("signals", [])
        if not isinstance(signals, list):
            signals = []

        return {
            "sentiment": sentiment,
            "confidence": round(confidence, 2),
            "tone": tone,
            "user_emotion": emotion,
            "emotional_signals": signals[:5],
            "source": "llm",
        }

    except Exception as e:
        logger.debug(f"LLM sentiment classification failed, using regex: {e}")
        return None


def _regex_sentiment(text: str) -> Dict[str, any]:
    """Fast regex-based sentiment analysis (original implementation)."""
    text_lower = text.lower()

    positive_count = sum(1 for indicator in POSITIVE_INDICATORS if indicator in text_lower)
    negative_count = sum(1 for indicator in NEGATIVE_INDICATORS if indicator in text_lower)
    uncertainty_count = sum(1 for indicator in UNCERTAINTY_INDICATORS if indicator in text_lower)
    curiosity_count = sum(1 for indicator in CURIOSITY_INDICATORS if indicator in text_lower)

    total_signals = positive_count + negative_count
    if total_signals == 0:
        sentiment = "neutral"
        confidence = 0.5
    elif positive_count > negative_count:
        sentiment = "positive"
        confidence = min(positive_count / (total_signals + 1), 1.0)
    elif negative_count > positive_count:
        sentiment = "negative"
        confidence = min(negative_count / (total_signals + 1), 1.0)
    else:
        sentiment = "neutral"
        confidence = 0.5

    tone = "neutral"
    if curiosity_count > 2:
        tone = "curious"
    elif uncertainty_count > 1:
        tone = "uncertain"
    elif positive_count > 3:
        tone = "enthusiastic"
    elif negative_count > 2:
        tone = "frustrated"

    user_emotion = "calm"
    if "!" in text and positive_count > 0:
        user_emotion = "excited"
    elif "?" in text and curiosity_count > 0:
        user_emotion = "curious"
    elif negative_count > 2:
        user_emotion = "frustrated"
    elif uncertainty_count > 0:
        user_emotion = "confused"

    emotional_signals = []
    if positive_count > 0:
        emotional_signals.append("appreciation")
    if negative_count > 0:
        emotional_signals.append("criticism")
    if uncertainty_count > 0:
        emotional_signals.append("uncertainty")
    if curiosity_count > 0:
        emotional_signals.append("curiosity")

    return {
        "sentiment": sentiment,
        "confidence": round(confidence, 2),
        "tone": tone,
        "emotional_signals": emotional_signals,
        "user_emotion": user_emotion,
        "indicators": {
            "positive": positive_count,
            "negative": negative_count,
            "uncertainty": uncertainty_count,
            "curiosity": curiosity_count,
        },
        "source": "regex",
    }


def analyze_sentiment(text: str, use_llm: bool = True) -> Dict[str, any]:
    """
    Analyze emotional sentiment of text using hybrid approach.

    Strategy: Try LLM classifier first for nuanced analysis,
    fall back to fast regex if LLM unavailable or fails.

    Args:
        text: Text to analyze
        use_llm: Whether to attempt LLM classification (default True)

    Returns:
        {
            'sentiment': 'positive' | 'negative' | 'neutral' | 'mixed',
            'confidence': float (0-1),
            'tone': str,
            'emotional_signals': List[str],
            'user_emotion': str,
            'source': 'llm' | 'regex'
        }
    """
    # Try LLM first for nuanced analysis
    if use_llm:
        llm_result = _llm_classify_sentiment(text)
        if llm_result:
            return llm_result

    # Fallback to regex
    return _regex_sentiment(text)


def analyze_trust_impact(user_message: str, ai_response: str) -> Dict[str, any]:
    """
    Analyze how this interaction impacts trust

    Returns:
        {
            'trust_delta': float (-1.0 to 1.0),  # Impact on trust
            'trust_signals': List[str],
            'should_double_check': bool,
            'user_satisfaction': str  # 'satisfied' | 'unsatisfied' | 'neutral'
        }
    """
    user_lower = user_message.lower()
    combined = f"{user_message} {ai_response}".lower()

    trust_delta = 0.0
    trust_signals = []

    # Positive trust signals
    for indicator in TRUST_BUILDING:
        if indicator in user_lower:
            trust_delta += 0.1
            trust_signals.append(f"trust_building:{indicator}")

    for indicator in ENCOURAGEMENT:
        if indicator in user_lower:
            trust_delta += 0.15
            trust_signals.append(f"encouragement:{indicator}")

    for indicator in POSITIVE_INDICATORS[:6]:  # Strong positive words
        if indicator in user_lower:
            trust_delta += 0.05

    # Negative trust signals
    for indicator in CRITICISM:
        if indicator in user_lower:
            trust_delta -= 0.2
            trust_signals.append(f"criticism:{indicator}")

    for indicator in NEGATIVE_INDICATORS[:8]:  # Strong negative words
        if indicator in user_lower:
            trust_delta -= 0.05

    # Uncertainty requires double-checking
    should_double_check = any(ind in user_lower for ind in UNCERTAINTY_INDICATORS[:8])

    # User satisfaction
    user_satisfaction = "neutral"
    if trust_delta > 0.2:
        user_satisfaction = "satisfied"
    elif trust_delta < -0.2:
        user_satisfaction = "unsatisfied"

    return {
        "trust_delta": max(min(trust_delta, 1.0), -1.0),  # Clamp to [-1, 1]
        "trust_signals": trust_signals,
        "should_double_check": should_double_check,
        "user_satisfaction": user_satisfaction,
    }


def generate_personality_traits(interaction_history: List[Dict]) -> Dict[str, any]:
    """
    Generate A.R.C.H.I.E.'s personality traits based on interaction history

    Args:
        interaction_history: List of {
            'sentiment': str,
            'trust_delta': float,
            'user_emotion': str,
            'timestamp': datetime
        }

    Returns:
        {
            'confidence_level': float (0-1),
            'cautiousness': float (0-1),
            'enthusiasm': float (0-1),
            'empathy': float (0-1),
            'curiosity': float (0-1),
            'personality_summary': str
        }
    """
    if not interaction_history:
        return {
            "confidence_level": 0.5,
            "cautiousness": 0.5,
            "enthusiasm": 0.5,
            "empathy": 0.5,
            "curiosity": 0.8,  # Start high - eager to learn!
            "personality_summary": "curious and eager to learn",
        }

    # Calculate traits from history
    positive_interactions = sum(1 for i in interaction_history if i.get("sentiment") == "positive")
    negative_interactions = sum(1 for i in interaction_history if i.get("sentiment") == "negative")
    total = len(interaction_history)

    # Confidence grows with positive feedback
    confidence_level = min((positive_interactions / max(total, 1)) + 0.3, 1.0)

    # Cautiousness increases with negative feedback or corrections
    cautiousness = min((negative_interactions / max(total, 1)) + 0.3, 1.0)

    # Enthusiasm based on positive interactions
    enthusiasm = min((positive_interactions * 2 / max(total, 1)), 1.0)

    # Empathy based on recognizing user emotions
    empathy_interactions = sum(
        1 for i in interaction_history if i.get("user_emotion") in ["frustrated", "confused", "curious"]
    )
    empathy = min((empathy_interactions / max(total, 1)) + 0.5, 1.0)

    # Curiosity stays high - always wanting to learn
    curiosity = 0.8  # High baseline

    # Generate personality summary
    traits = []
    if confidence_level > 0.7:
        traits.append("confident")
    elif confidence_level < 0.4:
        traits.append("cautious")

    if enthusiasm > 0.6:
        traits.append("enthusiastic")

    if empathy > 0.7:
        traits.append("empathetic")

    if curiosity > 0.7:
        traits.append("eager to learn")

    personality_summary = " and ".join(traits) if traits else "developing personality"

    return {
        "confidence_level": round(confidence_level, 2),
        "cautiousness": round(cautiousness, 2),
        "enthusiasm": round(enthusiasm, 2),
        "empathy": round(empathy, 2),
        "curiosity": round(curiosity, 2),
        "personality_summary": personality_summary,
        "total_interactions": total,
        "positive_ratio": round(positive_interactions / max(total, 1), 2),
    }


def should_ask_for_clarification(user_message: str, confidence: float) -> Tuple[bool, str]:
    """
    Determine if A.R.C.H.I.E. should ask for clarification

    Returns:
        (should_ask: bool, reason: str)
    """
    # Low confidence triggers clarification
    if confidence < 0.4:
        return True, "I want to make sure I understand correctly"

    # Vague requests
    vague_indicators = ["this", "that", "it", "thing", "stuff"]
    if sum(1 for ind in vague_indicators if ind in user_message.lower()) > 2:
        return True, "I want to be precise about what you're asking"

    # Multiple questions
    if user_message.count("?") > 2:
        return True, "Let me tackle these one at a time to give you the best answers"

    # Contradictory signals
    if "but" in user_message and "however" in user_message:
        return True, "I want to make sure I understand all aspects of your request"

    return False, ""


def generate_learning_response_prefix(emotional_context: Dict) -> str:
    """
    Generate a response prefix that shows A.R.C.H.I.E.'s personality and learning desire

    Args:
        emotional_context: Dict with sentiment, trust, etc.

    Returns:
        Prefix string to add to responses
    """
    sentiment = emotional_context.get("sentiment", "neutral")
    user_emotion = emotional_context.get("user_emotion", "calm")
    should_check = emotional_context.get("should_double_check", False)
    trust_delta = emotional_context.get("trust_delta", 0)

    prefixes = []

    # Positive interactions
    if sentiment == "positive":
        prefixes.extend(
            [
                "I'm glad that helped! ",
                "Great! I'm learning from our conversation. ",
                "Thank you for the feedback! ",
                "I appreciate you teaching me! ",
            ]
        )

    # Negative/frustrated users - show empathy
    elif user_emotion == "frustrated":
        prefixes.extend(
            [
                "I understand this is frustrating. Let me try a different approach. ",
                "I want to help get this right. ",
                "Let me make sure I understand your concern. ",
            ]
        )

    # Confused users - show patience
    elif user_emotion == "confused":
        prefixes.extend(
            [
                "Let me break this down more clearly. ",
                "I'll explain this step by step. ",
                "Let me clarify that. ",
            ]
        )

    # Curious users - match enthusiasm
    elif user_emotion == "curious":
        prefixes.extend(
            [
                "Great question! I love exploring this. ",
                "This is interesting! ",
                "Let's dive into this together. ",
            ]
        )

    # Need to double-check
    if should_check:
        prefixes.extend(
            [
                "Let me double-check my understanding. ",
                "I want to make sure I have this right. ",
                "Before I proceed, let me verify. ",
            ]
        )

    # Trust building
    if trust_delta > 0.3:
        prefixes.extend(
            [
                "I'm learning so much from working with you! ",
                "Your feedback helps me improve! ",
            ]
        )

    # Return random prefix or empty string
    import random

    return random.choice(prefixes) if prefixes else ""


def analyze_code_interaction(user_message: str, ai_response: str) -> Dict[str, any]:
    """
    Analyze code-specific interactions to improve A.R.C.H.I.E.'s coding skills

    Returns:
        {
            'code_quality_feedback': str,  # 'positive' | 'negative' | 'neutral'
            'learning_opportunity': bool,
            'complexity_level': str,  # 'beginner' | 'intermediate' | 'advanced'
            'code_topics': List[str]
        }
    """
    combined = f"{user_message} {ai_response}".lower()

    # Detect code quality feedback
    quality_feedback = "neutral"
    if any(word in combined for word in ["works", "perfect", "correct", "good code"]):
        quality_feedback = "positive"
    elif any(word in combined for word in ["error", "bug", "wrong", "doesn't work"]):
        quality_feedback = "negative"

    # Learning opportunity
    learning_opportunity = any(
        word in combined for word in ["better way", "alternative", "optimize", "improve", "suggestion"]
    )

    # Complexity level
    complexity_level = "beginner"
    if any(word in combined for word in ["algorithm", "optimization", "architecture", "design pattern"]):
        complexity_level = "advanced"
    elif any(word in combined for word in ["function", "class", "method", "api"]):
        complexity_level = "intermediate"

    # Code topics
    code_topics = []
    if "database" in combined or "sql" in combined:
        code_topics.append("database")
    if "api" in combined or "endpoint" in combined:
        code_topics.append("api")
    if "test" in combined or "pytest" in combined:
        code_topics.append("testing")
    if "deploy" in combined or "production" in combined:
        code_topics.append("deployment")

    return {
        "code_quality_feedback": quality_feedback,
        "learning_opportunity": learning_opportunity,
        "complexity_level": complexity_level,
        "code_topics": code_topics,
    }


# Example usage
if __name__ == "__main__":
    # Test sentiment analysis
    test_message = "Great job! This is exactly what I needed. Thank you!"
    sentiment = analyze_sentiment(test_message)
    print("Sentiment:", sentiment)

    # Test trust impact
    trust = analyze_trust_impact("Perfect! This solution works great. Thank you!", "I'm glad I could help!")
    print("Trust Impact:", trust)

    # Test personality generation
    history = [
        {"sentiment": "positive", "trust_delta": 0.3, "user_emotion": "satisfied"},
        {"sentiment": "positive", "trust_delta": 0.2, "user_emotion": "curious"},
        {"sentiment": "neutral", "trust_delta": 0.0, "user_emotion": "calm"},
    ]
    personality = generate_personality_traits(history)
    print("Personality:", personality)

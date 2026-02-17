"""
Fitness Routes - AI Fitness Coach
Phase 7: Standalone Apps - Uses archie_bridge for local-first AI with team agents
Updated: 2026-01-21 - Now uses Wellness Coach via archie_bridge
"""

from flask import render_template, jsonify, request
from . import fitness_bp
import sys
import logging

# Add ai_bridge to path for archie_bridge import
sys.path.insert(0, "/mnt/archie_brain/ai_bridge")
try:
    from archie_bridge import archie_bridge

    BRIDGE_AVAILABLE = True
except ImportError:
    BRIDGE_AVAILABLE = False

try:
    from ai_bridge.bridge_dispatcher import get_dispatcher

    _dispatcher = get_dispatcher()
except Exception:
    _dispatcher = None

logger = logging.getLogger(__name__)

# Wellness Coach agent ID
FITNESS_AGENT_ID = 73

# Fallback Ollama endpoint (if bridge unavailable)
OLLAMA_URL = "http://localhost:11434"

# System prompt for fitness AI
FITNESS_SYSTEM_PROMPT = """You are FLEX, an energetic AI fitness coach. You provide workout guidance, nutrition tips, and motivation for fitness goals.

IMPORTANT RULES:
1. Always remind users to consult a doctor before starting new exercise programs
2. NEVER provide medical advice - only general fitness information
3. Recommend starting slowly for beginners
4. Emphasize proper form over intensity
5. Encourage rest days and recovery
6. Be motivating but realistic about fitness goals
7. Account for different fitness levels when giving advice

You can help with:
- Workout routines (strength, cardio, flexibility)
- Exercise form guidance
- Nutrition basics for fitness
- Goal setting and tracking
- Recovery and injury prevention tips
- Motivation and accountability

Keep responses energetic but safe. Use bullet points for exercises and steps.
Include sets, reps, and duration when suggesting workouts."""


@fitness_bp.route("/")
def index():
    """Fitness main page"""
    return render_template("tools/fitness.html")


@fitness_bp.route("/api/status")
def status():
    """API endpoint for module health check"""
    import requests as req

    # Check Ollama connection (fallback)
    ollama_healthy = False
    try:
        response = req.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        ollama_healthy = response.status_code == 200
    except:
        pass

    return jsonify(
        {
            "module": "fitness",
            "status": "active",
            "healthy": True,
            "bridge_available": BRIDGE_AVAILABLE,
            "ollama_connected": ollama_healthy,
            "agent": "Wellness Coach" if BRIDGE_AVAILABLE else "Direct Ollama",
            "message": (
                "FLEX Fitness Coach is ready via A.R.C.H.I.E. Bridge"
                if BRIDGE_AVAILABLE
                else "FLEX Fitness Coach is ready (fallback mode)"
            ),
        }
    )


@fitness_bp.route("/api/chat", methods=["POST"])
def chat():
    """Send message to fitness AI via archie_bridge"""
    data = request.get_json() or {}
    message = data.get("message", "")
    user_id = data.get("user_id", 1)
    fitness_level = data.get("fitness_level", "intermediate")

    if not message:
        return jsonify({"success": False, "error": "Message is required"}), 400

    # Enhance prompt with fitness level context
    context_message = f"[User fitness level: {fitness_level}]\n\n{message}"

    try:
        if BRIDGE_AVAILABLE:
            # Use archie_bridge with Wellness Coach
            result = archie_bridge(
                prompt=context_message,
                user_id=user_id,
                agent_id=FITNESS_AGENT_ID,
                system_prompt=FITNESS_SYSTEM_PROMPT,
                enable_memory=True,
                try_local_first=True,
                task_type="fitness_coaching",
            )

            if _dispatcher:
                try:
                    _dispatcher.log_external_call(
                        capability="conversation",
                        module_id="fitness",
                        model_used=result.get("model_used", ""),
                        success=bool(result.get("response")),
                    )
                except Exception:
                    pass

            if result.get("success"):
                ai_response = result.get("response", "").strip()

                # Add safety reminder if workout advice given
                if any(word in message.lower() for word in ["workout", "exercise", "routine", "train"]):
                    if "consult" not in ai_response.lower() and "doctor" not in ai_response.lower():
                        ai_response += "\n\n*Remember: Always warm up properly and consult a healthcare professional before starting any new exercise program.*"

                return jsonify(
                    {
                        "success": True,
                        "response": ai_response,
                        "model": result.get("model_used", "archie_bridge"),
                        "agent": "Wellness Coach",
                        "source": result.get("source", "ai_bridge"),
                        "tokens_used": result.get("tokens_used", 0),
                    }
                )
            else:
                logger.warning("archie_bridge returned error, falling back to direct Ollama")

        # Fallback: Direct Ollama call
        import requests as req

        _default_model = _dispatcher.get_model_for_capability("conversation") if _dispatcher else ""
        model = data.get("model") or _default_model
        context = f"\n[User fitness level: {fitness_level}]\n"
        response = req.post(
            f"{OLLAMA_URL}/api/generate",
            json={
                "model": model,
                "prompt": f"{FITNESS_SYSTEM_PROMPT}{context}\n\nUser: {message}\n\nFLEX:",
                "stream": False,
                "options": {"temperature": 0.7, "num_predict": 1200},
            },
            timeout=90,
        )

        if response.status_code == 200:
            result = response.json()
            ai_response = result.get("response", "").strip()

            # Add safety reminder if workout advice given
            if any(word in message.lower() for word in ["workout", "exercise", "routine", "train"]):
                if "consult" not in ai_response.lower() and "doctor" not in ai_response.lower():
                    ai_response += "\n\n*Remember: Always warm up properly and consult a healthcare professional before starting any new exercise program.*"

            return jsonify(
                {
                    "success": True,
                    "response": ai_response,
                    "model": model,
                    "agent": "Direct Ollama (fallback)",
                    "source": "ollama_direct",
                }
            )
        else:
            logger.error(f"Ollama error: {response.status_code}")
            return (
                jsonify({"success": False, "error": "AI service temporarily unavailable"}),
                503,
            )

    except Exception as e:
        logger.error(f"Fitness chat error: {str(e)}")
        return (
            jsonify({"success": False, "error": f"An unexpected error occurred: {str(e)}"}),
            500,
        )


@fitness_bp.route("/api/workout/generate", methods=["POST"])
def generate_workout():
    """Generate a custom workout routine"""
    data = request.get_json() or {}
    workout_type = data.get("type", "full_body")  # full_body, upper, lower, cardio, hiit
    duration = data.get("duration", 30)  # minutes
    equipment = data.get("equipment", ["none"])  # bodyweight, dumbbells, barbell, machine
    fitness_level = data.get("fitness_level", "intermediate")
    goals = data.get("goals", ["general_fitness"])

    prompt = f"""Generate a {duration}-minute {workout_type} workout for a {fitness_level} level person.

Available equipment: {', '.join(equipment)}
Goals: {', '.join(goals)}

Please provide:
1. Warm-up (5 minutes)
2. Main workout with exercises, sets, reps, and rest periods
3. Cool-down/stretching (5 minutes)

Format each exercise as:
- Exercise Name: X sets × X reps (or duration) | Rest: Xs

Include form tips for complex exercises."""

    try:
        _default_model = _dispatcher.get_model_for_capability("conversation") if _dispatcher else ""
        _workout_model = _default_model or "dolphin3-8k:latest"
        response = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={
                "model": _workout_model,
                "prompt": f"{FITNESS_SYSTEM_PROMPT}\n\n{prompt}\n\nFLEX:",
                "stream": False,
                "options": {"temperature": 0.6, "num_predict": 2000},
            },
            timeout=120,
        )

        if response.status_code == 200:
            result = response.json()
            if _dispatcher:
                try:
                    _dispatcher.log_external_call(
                        capability="conversation",
                        module_id="fitness",
                        model_used=_workout_model,
                        success=True,
                    )
                except Exception:
                    pass
            return jsonify(
                {
                    "success": True,
                    "workout": result.get("response", "").strip(),
                    "type": workout_type,
                    "duration": duration,
                }
            )
        else:
            return (
                jsonify(
                    {
                        "success": False,
                        "error": "Workout generation service unavailable",
                    }
                ),
                503,
            )

    except Exception as e:
        logger.error(f"Workout generation error: {str(e)}")
        return jsonify({"success": False, "error": "Could not generate workout"}), 500


@fitness_bp.route("/api/exercises", methods=["GET"])
def get_exercise_library():
    """Get exercise library by muscle group"""
    exercises = {
        "chest": [
            {"name": "Push-ups", "equipment": "bodyweight", "difficulty": "beginner"},
            {
                "name": "Bench Press",
                "equipment": "barbell",
                "difficulty": "intermediate",
            },
            {
                "name": "Dumbbell Flyes",
                "equipment": "dumbbells",
                "difficulty": "intermediate",
            },
            {
                "name": "Incline Push-ups",
                "equipment": "bodyweight",
                "difficulty": "beginner",
            },
            {
                "name": "Diamond Push-ups",
                "equipment": "bodyweight",
                "difficulty": "advanced",
            },
        ],
        "back": [
            {"name": "Pull-ups", "equipment": "bar", "difficulty": "intermediate"},
            {
                "name": "Bent-over Rows",
                "equipment": "dumbbells",
                "difficulty": "intermediate",
            },
            {
                "name": "Superman Hold",
                "equipment": "bodyweight",
                "difficulty": "beginner",
            },
            {"name": "Lat Pulldown", "equipment": "machine", "difficulty": "beginner"},
            {"name": "Deadlift", "equipment": "barbell", "difficulty": "advanced"},
        ],
        "legs": [
            {"name": "Squats", "equipment": "bodyweight", "difficulty": "beginner"},
            {"name": "Lunges", "equipment": "bodyweight", "difficulty": "beginner"},
            {"name": "Leg Press", "equipment": "machine", "difficulty": "intermediate"},
            {
                "name": "Romanian Deadlift",
                "equipment": "barbell",
                "difficulty": "intermediate",
            },
            {
                "name": "Bulgarian Split Squat",
                "equipment": "dumbbells",
                "difficulty": "advanced",
            },
        ],
        "shoulders": [
            {
                "name": "Shoulder Press",
                "equipment": "dumbbells",
                "difficulty": "intermediate",
            },
            {
                "name": "Lateral Raises",
                "equipment": "dumbbells",
                "difficulty": "beginner",
            },
            {
                "name": "Pike Push-ups",
                "equipment": "bodyweight",
                "difficulty": "intermediate",
            },
            {
                "name": "Front Raises",
                "equipment": "dumbbells",
                "difficulty": "beginner",
            },
        ],
        "core": [
            {"name": "Plank", "equipment": "bodyweight", "difficulty": "beginner"},
            {
                "name": "Bicycle Crunches",
                "equipment": "bodyweight",
                "difficulty": "beginner",
            },
            {
                "name": "Mountain Climbers",
                "equipment": "bodyweight",
                "difficulty": "intermediate",
            },
            {
                "name": "Hanging Leg Raises",
                "equipment": "bar",
                "difficulty": "advanced",
            },
            {
                "name": "Russian Twists",
                "equipment": "bodyweight",
                "difficulty": "intermediate",
            },
        ],
        "cardio": [
            {
                "name": "Jumping Jacks",
                "equipment": "bodyweight",
                "difficulty": "beginner",
            },
            {
                "name": "Burpees",
                "equipment": "bodyweight",
                "difficulty": "intermediate",
            },
            {"name": "High Knees", "equipment": "bodyweight", "difficulty": "beginner"},
            {"name": "Jump Rope", "equipment": "rope", "difficulty": "intermediate"},
            {"name": "Box Jumps", "equipment": "box", "difficulty": "advanced"},
        ],
    }

    muscle_group = request.args.get("muscle_group")
    if muscle_group and muscle_group in exercises:
        return jsonify(
            {
                "success": True,
                "muscle_group": muscle_group,
                "exercises": exercises[muscle_group],
            }
        )

    return jsonify({"success": True, "exercises": exercises})


@fitness_bp.route("/api/workout/log", methods=["POST"])
def log_workout():
    """Log a completed workout"""
    data = request.get_json() or {}
    workout_type = data.get("type", "general")
    duration = data.get("duration", 0)
    exercises = data.get("exercises", [])
    notes = data.get("notes", "")
    intensity = data.get("intensity", 5)  # 1-10 scale

    if duration <= 0:
        return (
            jsonify({"success": False, "error": "Duration must be greater than 0"}),
            400,
        )

    # In production, save to database
    # For now, just acknowledge
    return jsonify(
        {
            "success": True,
            "message": "Workout logged successfully!",
            "stats": {
                "duration": duration,
                "type": workout_type,
                "exercise_count": len(exercises),
                "intensity": intensity,
            },
            "motivation": get_workout_motivation(),
        }
    )


def get_workout_motivation():
    """Return random motivation message"""
    messages = [
        "💪 Great work! Every workout counts!",
        "🔥 You showed up and that's what matters!",
        "⚡ Another session in the books! Keep grinding!",
        "🏆 Consistency beats perfection. You're doing great!",
        "💯 Your future self will thank you for today!",
        "🚀 One step closer to your goals!",
    ]
    import random

    return random.choice(messages)


@fitness_bp.route("/api/nutrition/macros", methods=["POST"])
def calculate_macros():
    """Calculate recommended macros based on goals"""
    data = request.get_json() or {}
    weight = data.get("weight")  # kg
    height = data.get("height")  # cm
    age = data.get("age")
    gender = data.get("gender", "male")
    activity_level = data.get("activity_level", "moderate")  # sedentary, light, moderate, active, very_active
    goal = data.get("goal", "maintain")  # lose, maintain, gain

    if not all([weight, height, age]):
        return (
            jsonify({"success": False, "error": "Weight, height, and age are required"}),
            400,
        )

    # Calculate BMR using Mifflin-St Jeor
    if gender == "male":
        bmr = 10 * weight + 6.25 * height - 5 * age + 5
    else:
        bmr = 10 * weight + 6.25 * height - 5 * age - 161

    # Activity multipliers
    activity_multipliers = {
        "sedentary": 1.2,
        "light": 1.375,
        "moderate": 1.55,
        "active": 1.725,
        "very_active": 1.9,
    }

    tdee = bmr * activity_multipliers.get(activity_level, 1.55)

    # Adjust for goal
    if goal == "lose":
        calories = tdee - 500
    elif goal == "gain":
        calories = tdee + 300
    else:
        calories = tdee

    # Calculate macros (balanced approach)
    protein = weight * 2  # 2g per kg body weight
    fat = (calories * 0.25) / 9  # 25% calories from fat
    carbs = (calories - (protein * 4) - (fat * 9)) / 4

    return jsonify(
        {
            "success": True,
            "bmr": round(bmr),
            "tdee": round(tdee),
            "target_calories": round(calories),
            "macros": {
                "protein": round(protein),
                "carbs": round(carbs),
                "fat": round(fat),
            },
            "note": "These are estimates. Adjust based on your progress and consult a nutritionist for personalized advice.",
        }
    )


@fitness_bp.route("/api/models", methods=["GET"])
def get_available_models():
    """Get available AI models via BridgeDispatcher"""
    # Models come from the bridge dispatcher
    models = []
    if _dispatcher:
        try:
            status = _dispatcher.get_dispatch_status()
            seen = set()
            for station_info in status.get("stations", {}).values():
                for agent in station_info.get("agents", []):
                    m = agent.get("model", "")
                    if m and m not in seen:
                        models.append({"name": m, "size": 0, "modified": ""})
                        seen.add(m)
        except Exception:
            pass
    if not models:
        models = [{"name": "default", "size": 0, "modified": ""}]
    return jsonify({"success": True, "models": models})

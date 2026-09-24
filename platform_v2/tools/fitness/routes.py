"""
Fitness Routes - AI Fitness Coach
Phase 7: Standalone Apps - Uses archie_bridge for local-first AI with team agents
Updated: 2026-01-21 - Now uses Wellness Coach via archie_bridge
"""

from flask import render_template, jsonify, request
from flask_login import login_required, current_user
from . import fitness_bp
from tools._user_scope import authenticated_user_id


@fitness_bp.before_request
@login_required
def require_login():
    pass


from .services.fitness_service import (
    log_workout as svc_log_workout,
    delete_goal as svc_delete_goal,
    delete_workout as svc_delete_workout,
    get_workout_history,
    set_goal,
    get_goals,
    update_goal as svc_update_goal,
    update_workout as svc_update_workout,
    get_fitness_stats,
    schedule_workout,
    get_ai_context,
    calculate_macros as svc_calculate_macros,
)
import logging

from tools.department_hq.services.department_dispatcher import dispatch_json

BRIDGE_AVAILABLE = True

logger = logging.getLogger(__name__)

# Wellness Coach agent ID
FITNESS_AGENT_ID = 73

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
    return jsonify(
        {
            "module": "fitness",
            "status": "active",
            "healthy": True,
            "bridge_available": BRIDGE_AVAILABLE,
            "dispatcher_available": True,
            "agent": "Wellness Coach",
            "message": "FLEX Fitness Coach is ready via A.R.C.H.I.E. Bridge",
        }
    )


@fitness_bp.route("/api/chat", methods=["POST"])
def chat():
    """Send message to fitness AI via archie_bridge"""
    data = request.get_json() or {}
    message = data.get("message", "")
    user_id = authenticated_user_id(data.get("user_id"))
    fitness_level = data.get("fitness_level", "intermediate")

    if not message:
        return jsonify({"success": False, "error": "Message is required"}), 400

    # Inject DB context into system prompt
    ai_ctx = get_ai_context(user_id)
    enriched_system_prompt = FITNESS_SYSTEM_PROMPT + (f"\n\n{ai_ctx}" if ai_ctx else "")

    # Enhance prompt with fitness level context
    context_message = f"[User fitness level: {fitness_level}]\n\n{message}"

    try:
        result = dispatch_json(
            capability="support",
            prompt=context_message,
            module_id="fitness",
            system_prompt=enriched_system_prompt,
            user_id=user_id,
            local_only=True,
        )
        ai_response = result.get("response", "") if isinstance(result, dict) else str(result or "")
        ai_response = ai_response.strip()

        if not ai_response:
            logger.error("Fitness dispatch_json returned empty response")
            return jsonify({"success": False, "error": "AI service temporarily unavailable"}), 503

        # Add safety reminder if workout advice given
        if any(word in message.lower() for word in ["workout", "exercise", "routine", "train"]):
            if "consult" not in ai_response.lower() and "doctor" not in ai_response.lower():
                ai_response += "\n\n*Remember: Always warm up properly and consult a healthcare professional before starting any new exercise program.*"

        return jsonify(
            {
                "success": True,
                "response": ai_response,
                "model": result.get("model_used", "dhq") if isinstance(result, dict) else "dhq",
                "agent": "Wellness Coach",
                "source": "dhq_dispatcher",
                "tokens_used": result.get("tokens_used", 0) if isinstance(result, dict) else 0,
            }
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
        result = dispatch_json(
            capability="support",
            prompt=prompt,
            module_id="fitness",
            system_prompt=FITNESS_SYSTEM_PROMPT,
            user_id=authenticated_user_id(),
            local_only=True,
        )
        workout_text = result.get("response", "") if isinstance(result, dict) else str(result or "")
        workout_text = workout_text.strip()

        if not workout_text:
            return jsonify({"success": False, "error": "Workout generation service unavailable"}), 503

        return jsonify(
            {
                "success": True,
                "workout": workout_text,
                "type": workout_type,
                "duration": duration,
            }
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
    """Log a completed workout — persists to DB."""
    data = request.get_json() or {}
    workout_type = data.get("workout_type") or data.get("type", "general")
    duration = data.get("duration_min") or data.get("duration", 0)
    exercises = data.get("exercises", [])
    calories = data.get("calories", 0)
    notes = data.get("notes", "")
    user_id = authenticated_user_id(data.get("user_id"))

    if duration <= 0:
        return (
            jsonify({"success": False, "error": "Duration must be greater than 0"}),
            400,
        )

    try:
        result = svc_log_workout(user_id, workout_type, exercises, duration, calories, notes)
        return jsonify(
            {
                "success": True,
                "message": "Workout logged successfully!",
                "id": result["id"],
                "logged_at": result["logged_at"],
                "motivation": get_workout_motivation(),
            }
        )
    except Exception as e:
        logger.error(f"log_workout error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


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

    if any(value is None or value == "" for value in (weight, height, age)):
        return (
            jsonify({"success": False, "error": "Weight, height, and age are required"}),
            400,
        )

    try:
        weight = float(weight)
        height = float(height)
        age = int(age)
    except (TypeError, ValueError):
        return (
            jsonify(
                {
                    "success": False,
                    "error": "Weight, height, and age must be numeric",
                }
            ),
            400,
        )

    numeric_ranges = (
        ("Weight", weight, 20, 400, "kg"),
        ("Height", height, 100, 250, "cm"),
        ("Age", age, 10, 120, ""),
    )
    for label, value, minimum, maximum, unit in numeric_ranges:
        if value < minimum or value > maximum:
            unit_suffix = unit if unit else ""
            return (
                jsonify(
                    {
                        "success": False,
                        "error": f"{label} must be between {minimum} and {maximum}{unit_suffix}",
                    }
                ),
                400,
            )

    valid_genders = ("male", "female")
    if gender not in valid_genders:
        return (
            jsonify(
                {
                    "success": False,
                    "error": "Gender must be one of: male, female",
                }
            ),
            400,
        )

    valid_activity_levels = ("sedentary", "light", "moderate", "active", "very_active")
    if activity_level not in valid_activity_levels:
        return (
            jsonify(
                {
                    "success": False,
                    "error": ("Activity level must be one of: " "sedentary, light, moderate, active, very_active"),
                }
            ),
            400,
        )

    valid_goals = ("lose", "maintain", "gain")
    if goal not in valid_goals:
        return (
            jsonify(
                {
                    "success": False,
                    "error": "Goal must be one of: lose, maintain, gain",
                }
            ),
            400,
        )

    result = svc_calculate_macros(weight, height, age, gender, activity_level, goal)

    return jsonify(
        {
            "success": True,
            **result,
            "note": "These are estimates. Adjust based on your progress and consult a nutritionist for personalized advice.",
        }
    )


@fitness_bp.route("/api/models", methods=["GET"])
def get_available_models():
    """Return the default DHQ-routed model selector option."""
    models = [{"name": "default", "size": 0, "modified": ""}]
    return jsonify({"success": True, "models": models})


@fitness_bp.route("/api/workout/history", methods=["GET"])
def workout_history():
    """Return recent workout logs for current user."""
    user_id = authenticated_user_id(request.args.get("user_id"))
    limit = request.args.get("limit", 20, type=int)
    try:
        history = get_workout_history(user_id, limit=limit)
        return jsonify({"success": True, "history": history})
    except Exception as e:
        logger.error(f"workout_history error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@fitness_bp.route("/api/workout/<int:workout_id>", methods=["PUT"])
def update_workout(workout_id):
    """Update a workout log for the authenticated user."""
    data = request.get_json() or {}
    try:
        workout = svc_update_workout(current_user.id, workout_id, data)
        if workout is None:
            return jsonify({"success": False, "error": "Workout not found or no valid fields"}), 404
        return jsonify({"success": True, "workout": workout})
    except Exception as e:
        logger.error(f"update_workout error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@fitness_bp.route("/api/workout/<int:workout_id>", methods=["DELETE"])
def delete_workout(workout_id):
    """Delete a workout log for the authenticated user."""
    try:
        deleted = svc_delete_workout(current_user.id, workout_id)
        if not deleted:
            return jsonify({"success": False, "error": "Workout not found"}), 404
        return jsonify({"success": True, "deleted": True})
    except Exception as e:
        logger.error(f"delete_workout error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@fitness_bp.route("/api/goals", methods=["POST"])
def create_goal():
    """Create a new fitness goal."""
    data = request.get_json() or {}
    user_id = authenticated_user_id(data.get("user_id"))
    goal_type = data.get("goal_type", "")
    target = data.get("target")
    unit = data.get("unit", "")
    deadline = data.get("deadline")

    if not goal_type or target is None:
        return jsonify({"success": False, "error": "goal_type and target are required"}), 400

    try:
        result = set_goal(user_id, goal_type, target, unit, deadline)
        return jsonify({"success": True, **result})
    except Exception as e:
        logger.error(f"create_goal error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@fitness_bp.route("/api/goals", methods=["GET"])
def list_goals():
    """List all fitness goals for current user."""
    user_id = authenticated_user_id(request.args.get("user_id"))
    try:
        goals = get_goals(user_id)
        return jsonify({"success": True, "goals": goals})
    except Exception as e:
        logger.error(f"list_goals error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@fitness_bp.route("/api/goals/<int:goal_id>", methods=["PUT"])
def update_goal(goal_id):
    """Update a fitness goal for the authenticated user."""
    data = request.get_json() or {}
    try:
        goal = svc_update_goal(current_user.id, goal_id, data)
        if goal is None:
            return jsonify({"success": False, "error": "Goal not found or no valid fields"}), 404
        return jsonify({"success": True, "goal": goal})
    except Exception as e:
        logger.error(f"update_goal error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@fitness_bp.route("/api/goals/<int:goal_id>", methods=["DELETE"])
def delete_goal(goal_id):
    """Delete a fitness goal for the authenticated user."""
    try:
        deleted = svc_delete_goal(current_user.id, goal_id)
        if not deleted:
            return jsonify({"success": False, "error": "Goal not found"}), 404
        return jsonify({"success": True, "deleted": True})
    except Exception as e:
        logger.error(f"delete_goal error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@fitness_bp.route("/api/schedule", methods=["POST"])
def schedule():
    """Schedule a workout via Google Calendar (or local fallback)."""
    data = request.get_json() or {}
    user_id = authenticated_user_id(data.get("user_id"))
    title = data.get("title", "Workout")
    datetime_str = data.get("datetime", "")
    duration = data.get("duration", 60)

    if not datetime_str:
        return jsonify({"success": False, "error": "datetime is required"}), 400

    try:
        result = schedule_workout(user_id, title, datetime_str, duration)
        return jsonify({"success": True, "result": result})
    except Exception as e:
        logger.error(f"schedule error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@fitness_bp.route("/api/stats", methods=["GET"])
def stats():
    """Return aggregated fitness stats for current user."""
    user_id = authenticated_user_id(request.args.get("user_id"))
    try:
        data = get_fitness_stats(user_id)
        return jsonify({"success": True, **data})
    except Exception as e:
        logger.error(f"stats error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

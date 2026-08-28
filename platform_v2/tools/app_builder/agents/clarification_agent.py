"""
Clarification Agent - Interactive Requirement Gathering
Asks intelligent questions to understand user requirements

Purpose:
- Analyze vague/incomplete user prompts
- Generate targeted clarifying questions
- Guide users to provide all necessary details
- Minimize back-and-forth by asking smart questions

Author: A.R.C.H.I.E. Platform
Date: 2026-01-07
"""

from typing import List, Dict, Optional
import json
import re

from tools.department_hq.services.department_dispatcher import dispatch_json

AI_AVAILABLE = True


# ============================================================================
# CLARIFICATION TEMPLATES
# ============================================================================

CLARIFICATION_CATEGORIES = {
    "app_type": {
        "question": "What type of application do you want to build?",
        "options": [
            "Web Application (accessed via browser)",
            "REST API (backend only)",
            "Mobile App (iOS/Android)",
            "Desktop Application",
            "Command Line Tool (CLI)",
            "Other (please specify)",
        ],
        "required": True,
    },
    "core_features": {
        "question": "What are the core features your application needs?",
        "prompt": "Please list 3-5 main features (e.g., user authentication, data storage, payment processing)",
        "required": True,
    },
    "target_users": {
        "question": "Who will use this application?",
        "examples": [
            "Internal team",
            "External customers",
            "Public users",
            "Specific industry",
        ],
        "required": True,
    },
    "tech_preferences": {
        "question": "Do you have any technology preferences?",
        "options": [
            "No preference (let A.R.C.H.I.E. decide)",
            "Python backend (Flask/FastAPI)",
            "JavaScript/Node.js backend",
            "React frontend",
            "Vue.js frontend",
            "PostgreSQL database",
            "MongoDB database",
            "Other (please specify)",
        ],
        "required": False,
        "multiple": True,
    },
    "authentication": {
        "question": "Does your app need user authentication?",
        "options": [
            "Yes, with login/signup",
            "Yes, social login (Google/GitHub)",
            "No",
        ],
        "required": True,
    },
    "database": {
        "question": "Will your app need to store data?",
        "followup": "What kind of data? (e.g., user profiles, products, posts)",
        "required": True,
    },
    "deployment": {
        "question": "Where would you like to deploy this application?",
        "options": [
            "Cloud (Vercel, Railway, etc.) - Recommended",
            "Docker container",
            "Self-hosted server",
            "Not sure yet",
        ],
        "required": False,
    },
    "budget_timeline": {
        "question": "Any constraints on complexity or timeline?",
        "prompt": "This helps us scope the project appropriately",
        "required": False,
    },
}


# ============================================================================
# CLARIFICATION AGENT
# ============================================================================


class ClarificationAgent:
    """
    Intelligent agent that asks clarifying questions
    Uses LLM to understand prompts and generate targeted questions
    """

    def __init__(self, project_id: int, user_id: int):
        self.project_id = project_id
        self.user_id = user_id

    async def generate_questions(self, user_prompt: str) -> List[Dict]:
        """
        Analyze user prompt and generate clarifying questions

        Args:
            user_prompt: User's natural language description

        Returns:
            List of question dictionaries
        """
        # Analyze prompt to determine what's missing
        analysis = self._analyze_prompt(user_prompt)

        # Generate questions based on analysis
        questions = []

        # Always ask about app type if not clear
        if not analysis["has_app_type"]:
            questions.append(
                {
                    "id": "app_type",
                    "question": CLARIFICATION_CATEGORIES["app_type"]["question"],
                    "type": "choice",
                    "options": CLARIFICATION_CATEGORIES["app_type"]["options"],
                    "required": True,
                }
            )

        # Ask about core features if vague
        if not analysis["has_features"] or analysis["is_vague"]:
            questions.append(
                {
                    "id": "core_features",
                    "question": CLARIFICATION_CATEGORIES["core_features"]["question"],
                    "type": "text",
                    "prompt": CLARIFICATION_CATEGORIES["core_features"]["prompt"],
                    "required": True,
                }
            )

        # Ask about target users if not mentioned
        if not analysis["has_target_users"]:
            questions.append(
                {
                    "id": "target_users",
                    "question": CLARIFICATION_CATEGORIES["target_users"]["question"],
                    "type": "text",
                    "examples": CLARIFICATION_CATEGORIES["target_users"]["examples"],
                    "required": True,
                }
            )

        # Authentication question
        if not analysis["has_authentication"]:
            questions.append(
                {
                    "id": "authentication",
                    "question": CLARIFICATION_CATEGORIES["authentication"]["question"],
                    "type": "choice",
                    "options": CLARIFICATION_CATEGORIES["authentication"]["options"],
                    "required": True,
                }
            )

        # Database question
        if not analysis["has_database"]:
            questions.append(
                {
                    "id": "database",
                    "question": CLARIFICATION_CATEGORIES["database"]["question"],
                    "type": "text",
                    "followup": CLARIFICATION_CATEGORIES["database"]["followup"],
                    "required": True,
                }
            )

        # Tech preferences (optional)
        questions.append(
            {
                "id": "tech_preferences",
                "question": CLARIFICATION_CATEGORIES["tech_preferences"]["question"],
                "type": "multiple_choice",
                "options": CLARIFICATION_CATEGORIES["tech_preferences"]["options"],
                "required": False,
            }
        )

        # Use AI to generate additional smart questions
        if AI_AVAILABLE and len(questions) < 3:
            ai_questions = await self._generate_ai_questions(user_prompt, analysis)
            questions.extend(ai_questions)

        # Limit to 5-7 questions max to avoid overwhelming user
        return questions[:7]

    def _analyze_prompt(self, prompt: str) -> Dict[str, bool]:
        """
        Analyze user prompt to detect what information is provided

        Args:
            prompt: User's natural language description

        Returns:
            Analysis dictionary
        """
        prompt_lower = prompt.lower()

        # App type detection
        app_type_keywords = {
            "web": ["web", "website", "webapp", "browser"],
            "api": ["api", "rest", "backend", "service"],
            "mobile": ["mobile", "ios", "android", "app store"],
            "desktop": ["desktop", "electron", "native"],
            "cli": ["cli", "command line", "terminal", "script"],
        }

        has_app_type = any(
            any(keyword in prompt_lower for keyword in keywords) for keywords in app_type_keywords.values()
        )

        # Feature detection
        feature_indicators = [
            "feature",
            "functionality",
            "need",
            "want",
            "should",
            "must",
            "allow",
            "enable",
            "support",
            "include",
        ]
        has_features = any(indicator in prompt_lower for indicator in feature_indicators)

        # Target users detection
        user_keywords = [
            "user",
            "customer",
            "client",
            "people",
            "team",
            "public",
            "internal",
        ]
        has_target_users = any(keyword in prompt_lower for keyword in user_keywords)

        # Authentication detection
        auth_keywords = [
            "auth",
            "login",
            "signup",
            "register",
            "account",
            "password",
            "oauth",
        ]
        has_authentication = any(keyword in prompt_lower for keyword in auth_keywords)

        # Database detection
        db_keywords = [
            "database",
            "data",
            "store",
            "save",
            "persist",
            "postgres",
            "mongodb",
            "mysql",
        ]
        has_database = any(keyword in prompt_lower for keyword in db_keywords)

        # Technology detection
        tech_keywords = [
            "python",
            "javascript",
            "react",
            "flask",
            "fastapi",
            "node",
            "vue",
            "angular",
        ]
        has_tech_preferences = any(keyword in prompt_lower for keyword in tech_keywords)

        # Vagueness detection
        vague_indicators = ["simple", "basic", "small", "quick", "something", "maybe"]
        is_vague = any(indicator in prompt_lower for indicator in vague_indicators) or len(prompt.split()) < 10

        return {
            "has_app_type": has_app_type,
            "has_features": has_features,
            "has_target_users": has_target_users,
            "has_authentication": has_authentication,
            "has_database": has_database,
            "has_tech_preferences": has_tech_preferences,
            "is_vague": is_vague,
            "word_count": len(prompt.split()),
        }

    async def _generate_ai_questions(self, user_prompt: str, analysis: Dict) -> List[Dict]:
        """
        Use AI to generate additional clarifying questions

        Args:
            user_prompt: User's original prompt
            analysis: Analysis of the prompt

        Returns:
            List of AI-generated questions
        """
        if not AI_AVAILABLE:
            return []

        try:
            # Prepare context for AI
            context = {
                "user_prompt": user_prompt,
                "analysis": analysis,
                "task": "clarification",
            }

            # Prompt for AI
            ai_prompt = f"""Analyze this app building request and generate 1-2 specific clarifying questions:

User Request: "{user_prompt}"

Analysis:
- Has app type: {analysis['has_app_type']}
- Has features: {analysis['has_features']}
- Is vague: {analysis['is_vague']}

Generate questions that will help understand:
1. Specific functionality requirements
2. Scale/complexity expectations
3. Any unique constraints or requirements

Format as JSON array:
[
    {{
        "id": "unique_id",
        "question": "Question text?",
        "type": "text",
        "required": true
    }}
]"""

            # Call AI via DHQ dispatcher (ADR-013)
            result = dispatch_json(capability="research", prompt=ai_prompt, module_id="app_builder")

            if result.get("success") and result.get("response"):
                # Parse JSON response
                response_text = result["response"]

                # Extract JSON from response
                json_match = re.search(r"\[.*\]", response_text, re.DOTALL)
                if json_match:
                    questions = json.loads(json_match.group(0))
                    return questions[:2]  # Max 2 AI questions

        except Exception as e:
            print(f"[ClarificationAgent] AI question generation failed: {e}")

        return []

    def validate_answers(self, questions: List[Dict], answers: Dict) -> Dict[str, List[str]]:
        """
        Validate user answers to clarification questions

        Args:
            questions: List of questions that were asked
            answers: Dictionary of answers provided

        Returns:
            Dictionary of validation errors (empty if valid)
        """
        errors = {}

        for question in questions:
            question_id = question["id"]
            required = question.get("required", False)

            # Check if answer provided
            answer = answers.get(question_id)

            if required and not answer:
                errors[question_id] = ["This question is required"]
                continue

            # Type-specific validation
            if answer:
                question_type = question.get("type", "text")

                if question_type == "choice":
                    # Validate against options
                    options = question.get("options", [])
                    if answer not in options:
                        errors[question_id] = ["Invalid choice"]

                elif question_type == "multiple_choice":
                    # Validate multiple selections
                    if not isinstance(answer, list):
                        errors[question_id] = ["Must be a list of choices"]
                    else:
                        options = question.get("options", [])
                        invalid = [a for a in answer if a not in options]
                        if invalid:
                            errors[question_id] = ["Invalid choices selected"]

                elif question_type == "text":
                    # Validate text length
                    if len(str(answer).strip()) < 3:
                        errors[question_id] = ["Answer too short"]

        return errors

    async def save_to_database(self, questions: List[Dict], answers: Optional[Dict] = None):
        """
        Save clarification questions and answers to database

        Args:
            questions: List of questions
            answers: Dictionary of answers (optional)
        """
        try:
            from app import get_db

            conn = get_db()
            cur = conn.cursor()

            # Save to chat history
            for question in questions:
                cur.execute(
                    """
                    INSERT INTO app_builder_chat_history
                    (project_id, user_id, role, message, message_type, step, agent)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                    (
                        self.project_id,
                        self.user_id,
                        "assistant",
                        question["question"],
                        "clarification",
                        "planning",
                        "clarification_agent",
                    ),
                )

            # Save answers if provided
            if answers:
                for question in questions:
                    question_id = question["id"]
                    answer = answers.get(question_id)

                    if answer:
                        cur.execute(
                            """
                            INSERT INTO app_builder_chat_history
                            (project_id, user_id, role, message, message_type, step, agent, metadata)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                            (
                                self.project_id,
                                self.user_id,
                                "user",
                                str(answer),
                                "clarification",
                                "planning",
                                "clarification_agent",
                                json.dumps({"question_id": question_id}),
                            ),
                        )

            conn.commit()

        except Exception as e:
            print(f"[ClarificationAgent] Failed to save to database: {e}")
        finally:
            try:
                cur.close()
                conn.close()
            except Exception:
                pass


# ============================================================================
# TESTING
# ============================================================================

if __name__ == "__main__":
    print("=" * 80)
    print("CLARIFICATION AGENT TEST")
    print("=" * 80)

    agent = ClarificationAgent(project_id=1, user_id=1)

    # Test various prompts
    test_prompts = [
        "Build me a todo app",
        "I need a web application for managing customer data with authentication",
        "Create a REST API for a blog platform with posts, comments, and users using Python and PostgreSQL",
    ]

    for i, prompt in enumerate(test_prompts, 1):
        print(f"\n Test {i}: '{prompt}'")
        analysis = agent._analyze_prompt(prompt)
        print(f"  Analysis: {analysis}")

        # Note: Can't test async without running in async context
        # questions = await agent.generate_questions(prompt)
        # print(f"  Questions: {len(questions)}")

    print("\n✅ Clarification agent test complete")
    print("=" * 80)

"""
Cost Controller for ARCHIE Consciousness Intelligence

Tracks API usage, enforces daily limits, and estimates batch processing costs.
Uses api_usage_daily table for persistent tracking.

Usage:
    from ai_bridge.cost_controller import get_cost_controller, can_process_batch

    controller = get_cost_controller()

    # Check if we can process
    if controller.can_spend_tokens(estimated_tokens):
        # Process...
        controller.record_usage(input_tokens, output_tokens)

    # Get status
    status = controller.get_daily_status()
"""

import logging
from datetime import date, datetime
from typing import Optional
from dataclasses import dataclass
from psycopg2.extras import RealDictCursor
from db import get_db

logger = logging.getLogger(__name__)

# Configuration - Claude API pricing (as of 2025)
# Claude 3.5 Sonnet: $3/1M input, $15/1M output
CLAUDE_INPUT_COST_PER_1M = 3.00
CLAUDE_OUTPUT_COST_PER_1M = 15.00

# Daily limits
DAILY_TOKEN_LIMIT = 500_000  # 500K tokens/day
DAILY_COST_LIMIT_USD = 7.50  # ~$7.50/day max

# Token estimation constants
TOKENS_PER_CONVERSATION = 2000  # Average tokens to analyze a conversation
TOKENS_PER_GITHUB_FILE = 1500  # Average tokens for code file analysis
OUTPUT_RATIO = 0.3  # Output is typically 30% of input for analysis tasks


@dataclass
class UsageStatus:
    """Current usage status for the day"""

    date: date
    input_tokens: int
    output_tokens: int
    total_tokens: int
    requests: int
    estimated_cost_usd: float
    remaining_tokens: int
    remaining_budget_usd: float
    can_process: bool
    limit_reached: bool


@dataclass
class BatchEstimate:
    """Estimated cost for a batch operation"""

    item_count: int
    estimated_input_tokens: int
    estimated_output_tokens: int
    estimated_total_tokens: int
    estimated_cost_usd: float
    within_daily_limit: bool
    would_exceed_by_tokens: int
    would_exceed_by_usd: float


class CostController:
    """Controls API usage and costs for knowledge processing"""

    def __init__(
        self,
        daily_token_limit: int = DAILY_TOKEN_LIMIT,
        daily_cost_limit: float = DAILY_COST_LIMIT_USD,
    ):
        self.daily_token_limit = daily_token_limit
        self.daily_cost_limit = daily_cost_limit

    def _ensure_daily_record(self, conn) -> None:
        """Ensure a record exists for today"""
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO api_usage_daily (date)
            VALUES (%s)
            ON CONFLICT (date) DO NOTHING
            """,
            (date.today(),),
        )
        conn.commit()
        cur.close()

    def _get_today_usage(self, conn) -> dict:
        """Get today's usage from database"""
        self._ensure_daily_record(conn)
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            """
            SELECT * FROM api_usage_daily WHERE date = %s
            """,
            (date.today(),),
        )
        row = cur.fetchone()
        cur.close()
        return dict(row) if row else {}

    def get_daily_status(self) -> UsageStatus:
        """Get current daily usage status"""
        try:
            conn = get_db()
            try:
                usage = self._get_today_usage(conn)
            finally:
                try:
                    conn.close()
                except Exception:
                    pass

            input_tokens = usage.get("claude_input_tokens", 0) or 0
            output_tokens = usage.get("claude_output_tokens", 0) or 0
            total_tokens = input_tokens + output_tokens
            requests = usage.get("claude_requests", 0) or 0
            estimated_cost = float(usage.get("estimated_cost_usd", 0) or 0)

            remaining_tokens = max(0, self.daily_token_limit - total_tokens)
            remaining_budget = max(0, self.daily_cost_limit - estimated_cost)

            can_process = remaining_tokens > 0 and remaining_budget > 0
            limit_reached = total_tokens >= self.daily_token_limit or estimated_cost >= self.daily_cost_limit

            return UsageStatus(
                date=date.today(),
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
                requests=requests,
                estimated_cost_usd=estimated_cost,
                remaining_tokens=remaining_tokens,
                remaining_budget_usd=remaining_budget,
                can_process=can_process,
                limit_reached=limit_reached,
            )
        except Exception as e:
            logger.error(f"Error getting daily status: {e}")
            # Return conservative defaults on error
            return UsageStatus(
                date=date.today(),
                input_tokens=0,
                output_tokens=0,
                total_tokens=0,
                requests=0,
                estimated_cost_usd=0,
                remaining_tokens=0,
                remaining_budget_usd=0,
                can_process=False,
                limit_reached=True,
            )

    def can_spend_tokens(self, estimated_tokens: int) -> bool:
        """Check if we can spend the estimated tokens within limits"""
        status = self.get_daily_status()
        return status.remaining_tokens >= estimated_tokens

    def estimate_batch(
        self,
        item_count: int,
        category: str = "conversation",
    ) -> BatchEstimate:
        """
        Estimate cost for processing a batch of items.

        Args:
            item_count: Number of items to process
            category: Type of items ('conversation', 'github', 'claude_hook')

        Returns:
            BatchEstimate with cost projections
        """
        # Estimate tokens based on category
        if category == "conversation":
            tokens_per_item = TOKENS_PER_CONVERSATION
        elif category == "github":
            tokens_per_item = TOKENS_PER_GITHUB_FILE
        else:
            tokens_per_item = 1000  # Default conservative estimate

        estimated_input = item_count * tokens_per_item
        estimated_output = int(estimated_input * OUTPUT_RATIO)
        estimated_total = estimated_input + estimated_output

        # Calculate cost
        input_cost = (estimated_input / 1_000_000) * CLAUDE_INPUT_COST_PER_1M
        output_cost = (estimated_output / 1_000_000) * CLAUDE_OUTPUT_COST_PER_1M
        estimated_cost = input_cost + output_cost

        # Check against limits
        status = self.get_daily_status()
        within_limit = estimated_total <= status.remaining_tokens and estimated_cost <= status.remaining_budget_usd

        would_exceed_tokens = max(0, estimated_total - status.remaining_tokens)
        would_exceed_usd = max(0, estimated_cost - status.remaining_budget_usd)

        return BatchEstimate(
            item_count=item_count,
            estimated_input_tokens=estimated_input,
            estimated_output_tokens=estimated_output,
            estimated_total_tokens=estimated_total,
            estimated_cost_usd=round(estimated_cost, 4),
            within_daily_limit=within_limit,
            would_exceed_by_tokens=would_exceed_tokens,
            would_exceed_by_usd=round(would_exceed_usd, 4),
        )

    def record_usage(
        self,
        input_tokens: int,
        output_tokens: int,
        embedding_tokens: int = 0,
    ) -> bool:
        """
        Record API usage for today.

        Args:
            input_tokens: Claude input tokens used
            output_tokens: Claude output tokens used
            embedding_tokens: Ollama embedding tokens (free, but tracked)

        Returns:
            True if recorded successfully
        """
        try:
            # Calculate cost
            input_cost = (input_tokens / 1_000_000) * CLAUDE_INPUT_COST_PER_1M
            output_cost = (output_tokens / 1_000_000) * CLAUDE_OUTPUT_COST_PER_1M
            total_cost = input_cost + output_cost

            conn = get_db()
            try:
                self._ensure_daily_record(conn)

                cur = conn.cursor()
                cur.execute(
                    """
                    UPDATE api_usage_daily SET
                        claude_input_tokens = claude_input_tokens + %s,
                        claude_output_tokens = claude_output_tokens + %s,
                        claude_requests = claude_requests + 1,
                        ollama_embedding_tokens = ollama_embedding_tokens + %s,
                        estimated_cost_usd = estimated_cost_usd + %s,
                        updated_at = NOW()
                    WHERE date = %s
                    """,
                    (
                        input_tokens,
                        output_tokens,
                        embedding_tokens,
                        total_cost,
                        date.today(),
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

            logger.info(f"Recorded usage: {input_tokens} in, {output_tokens} out, " f"${total_cost:.4f} cost")
            return True

        except Exception as e:
            logger.error(f"Error recording usage: {e}")
            return False

    def get_usage_history(self, days: int = 7) -> list[dict]:
        """Get usage history for the last N days"""
        try:
            conn = get_db()
            try:
                cur = conn.cursor(cursor_factory=RealDictCursor)
                cur.execute(
                    """
                    SELECT * FROM api_usage_daily
                    ORDER BY date DESC
                    LIMIT %s
                    """,
                    (days,),
                )
                rows = cur.fetchall()
                return [dict(r) for r in rows]
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
            logger.error(f"Error getting usage history: {e}")
            return []


# Singleton instance
_cost_controller: Optional[CostController] = None


def get_cost_controller() -> CostController:
    """Get or create singleton cost controller instance"""
    global _cost_controller
    if _cost_controller is None:
        _cost_controller = CostController()
    return _cost_controller


def can_process_batch(item_count: int, category: str = "conversation") -> bool:
    """Convenience function to check if a batch can be processed"""
    controller = get_cost_controller()
    estimate = controller.estimate_batch(item_count, category)
    return estimate.within_daily_limit


def get_daily_cost_status() -> dict:
    """Convenience function to get daily status as dict"""
    controller = get_cost_controller()
    status = controller.get_daily_status()
    return {
        "date": str(status.date),
        "input_tokens": status.input_tokens,
        "output_tokens": status.output_tokens,
        "total_tokens": status.total_tokens,
        "requests": status.requests,
        "estimated_cost_usd": status.estimated_cost_usd,
        "remaining_tokens": status.remaining_tokens,
        "remaining_budget_usd": status.remaining_budget_usd,
        "can_process": status.can_process,
        "limit_reached": status.limit_reached,
        "daily_token_limit": DAILY_TOKEN_LIMIT,
        "daily_cost_limit_usd": DAILY_COST_LIMIT_USD,
    }


if __name__ == "__main__":
    # Test when run directly
    logging.basicConfig(level=logging.INFO)

    print("Testing Cost Controller...")
    print("-" * 40)

    controller = get_cost_controller()

    # Get status
    status = controller.get_daily_status()
    print(f"\nDaily Status:")
    print(f"  Date: {status.date}")
    print(f"  Tokens used: {status.total_tokens:,}")
    print(f"  Cost: ${status.estimated_cost_usd:.4f}")
    print(f"  Remaining tokens: {status.remaining_tokens:,}")
    print(f"  Remaining budget: ${status.remaining_budget_usd:.2f}")
    print(f"  Can process: {status.can_process}")

    # Estimate batch
    estimate = controller.estimate_batch(10, "conversation")
    print(f"\nBatch Estimate (10 conversations):")
    print(f"  Estimated tokens: {estimate.estimated_total_tokens:,}")
    print(f"  Estimated cost: ${estimate.estimated_cost_usd:.4f}")
    print(f"  Within limit: {estimate.within_daily_limit}")

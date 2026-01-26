"""
Pool Management Module (Admin Only)
Status: Coming Soon

Full management interface for Archie Pool:
- Miners management (list, ban/unban, details)
- Payouts processing (manual triggers, stuck payouts)
- Conversions dashboard (queue, rates, history)
- Analytics (hashrate, revenue, miner growth)
- Pool settings (fees, PPLNS window, notifications)
"""

from flask import Blueprint

pool_management_bp = Blueprint('pool_management', __name__, url_prefix='/tools/pool-management')

from . import routes

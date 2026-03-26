"""Accounting plugin routes — chart of accounts, transactions, expenses, reports."""

import logging

from flask import g, jsonify, render_template, request
from flask_login import login_required
from psycopg2.extras import Json

from core.database import get_db_cursor, set_tenant_search_path
from core.event_bus import event_bus
from core.tenant import require_module

logger = logging.getLogger(__name__)


def register_routes(bp):
    """Attach all Accounting routes to the given blueprint."""

    # ------------------------------------------------------------------
    # Dashboard
    # ------------------------------------------------------------------

    @bp.route("/")
    @login_required
    @require_module("accounting")
    def index():
        return render_template("accounting.html")

    # ------------------------------------------------------------------
    # Chart of Accounts
    # ------------------------------------------------------------------

    @bp.route("/api/accounts", methods=["GET"])
    @login_required
    @require_module("accounting")
    def list_accounts():
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                SELECT id, code, name, account_type, sub_type, description,
                       is_active, parent_id, balance, created_at
                FROM chart_of_accounts
                ORDER BY code
                """
            )
            rows = cur.fetchall()

        # Group by account_type for a tree-like response
        grouped = {}
        for row in rows:
            atype = row["account_type"]
            grouped.setdefault(atype, []).append(row)

        return jsonify({"accounts": rows, "grouped": grouped})

    @bp.route("/api/accounts", methods=["POST"])
    @login_required
    @require_module("accounting")
    def create_account():
        data = request.get_json(force=True)
        code = (data.get("code") or "").strip()
        name = (data.get("name") or "").strip()
        account_type = (data.get("account_type") or "").strip()

        if not code:
            return jsonify({"error": "code is required"}), 400
        if not name:
            return jsonify({"error": "name is required"}), 400
        if account_type not in ("asset", "liability", "equity", "revenue", "expense"):
            return jsonify({"error": "account_type must be asset/liability/equity/revenue/expense"}), 400

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                INSERT INTO chart_of_accounts (code, name, account_type, sub_type, description, parent_id)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id, code, name, account_type, sub_type, description, is_active, parent_id, balance, created_at
                """,
                (
                    code,
                    name,
                    account_type,
                    data.get("sub_type"),
                    data.get("description"),
                    data.get("parent_id"),
                ),
            )
            account = cur.fetchone()

        return jsonify(account), 201

    @bp.route("/api/accounts/<int:account_id>", methods=["PUT"])
    @login_required
    @require_module("accounting")
    def update_account(account_id):
        data = request.get_json(force=True)
        sets = []
        params = []

        for field in ("name", "sub_type", "description"):
            if field in data:
                sets.append(f"{field} = %s")
                params.append(data[field])
        if "is_active" in data:
            sets.append("is_active = %s")
            params.append(bool(data["is_active"]))
        if "parent_id" in data:
            sets.append("parent_id = %s")
            params.append(data["parent_id"])

        if not sets:
            return jsonify({"error": "no fields to update"}), 400

        params.append(account_id)

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                f"""
                UPDATE chart_of_accounts SET {', '.join(sets)}
                WHERE id = %s
                RETURNING id, code, name, account_type, sub_type, description, is_active, parent_id, balance, created_at
                """,
                params,
            )
            account = cur.fetchone()

        if account is None:
            return jsonify({"error": "account not found"}), 404

        return jsonify(account)

    @bp.route("/api/accounts/<int:account_id>/transactions", methods=["GET"])
    @login_required
    @require_module("accounting")
    def list_account_transactions(account_id):
        page = request.args.get("page", 1, type=int)
        per_page = request.args.get("per_page", 25, type=int)
        offset = (page - 1) * per_page

        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                "SELECT COUNT(*) AS cnt FROM transactions WHERE account_id = %s AND status != 'voided'",
                (account_id,),
            )
            total = cur.fetchone()["cnt"]
            cur.execute(
                """
                SELECT id, date, reference, description, amount, transaction_type,
                       category, account_id, customer_id, invoice_id, status, tags, created_at
                FROM transactions
                WHERE account_id = %s AND status != 'voided'
                ORDER BY date DESC, id DESC
                LIMIT %s OFFSET %s
                """,
                (account_id, per_page, offset),
            )
            txns = cur.fetchall()

        return jsonify({"transactions": txns, "total": total, "page": page, "per_page": per_page})

    # ------------------------------------------------------------------
    # Transactions
    # ------------------------------------------------------------------

    @bp.route("/api/transactions", methods=["GET"])
    @login_required
    @require_module("accounting")
    def list_transactions():
        page = request.args.get("page", 1, type=int)
        per_page = request.args.get("per_page", 25, type=int)
        offset = (page - 1) * per_page
        start_date = request.args.get("start_date")
        end_date = request.args.get("end_date")
        txn_type = request.args.get("type")
        account_id = request.args.get("account_id", type=int)

        where_clauses = ["status != 'voided'"]
        params: list = []

        if start_date:
            where_clauses.append("date >= %s")
            params.append(start_date)
        if end_date:
            where_clauses.append("date <= %s")
            params.append(end_date)
        if txn_type:
            where_clauses.append("transaction_type = %s")
            params.append(txn_type)
        if account_id:
            where_clauses.append("account_id = %s")
            params.append(account_id)

        where = "WHERE " + " AND ".join(where_clauses)

        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(f"SELECT COUNT(*) AS cnt FROM transactions {where}", params)
            total = cur.fetchone()["cnt"]
            cur.execute(
                f"""
                SELECT id, date, reference, description, amount, transaction_type,
                       category, account_id, customer_id, invoice_id, status, tags, metadata, created_at
                FROM transactions {where}
                ORDER BY date DESC, id DESC
                LIMIT %s OFFSET %s
                """,
                params + [per_page, offset],
            )
            txns = cur.fetchall()

        return jsonify({"transactions": txns, "total": total, "page": page, "per_page": per_page})

    @bp.route("/api/transactions", methods=["POST"])
    @login_required
    @require_module("accounting")
    def create_transaction():
        data = request.get_json(force=True)
        description = (data.get("description") or "").strip()
        txn_type = (data.get("transaction_type") or "").strip()

        if not description:
            return jsonify({"error": "description is required"}), 400
        if txn_type not in ("income", "expense", "transfer", "journal"):
            return jsonify({"error": "transaction_type must be income/expense/transfer/journal"}), 400

        try:
            amount = float(data.get("amount", 0))
        except (TypeError, ValueError):
            return jsonify({"error": "amount must be a number"}), 400

        txn_date = data.get("date") or None
        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            if txn_date:
                cur.execute(
                    """
                    INSERT INTO transactions
                        (date, reference, description, amount, transaction_type, category,
                         account_id, customer_id, invoice_id, tags, metadata)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id, date, reference, description, amount, transaction_type,
                              category, account_id, customer_id, invoice_id, status, tags, metadata, created_at
                    """,
                    (
                        txn_date,
                        data.get("reference"),
                        description,
                        amount,
                        txn_type,
                        data.get("category"),
                        data.get("account_id"),
                        data.get("customer_id"),
                        data.get("invoice_id"),
                        Json(data.get("tags", [])),
                        Json(data.get("metadata", {})),
                    ),
                )
            else:
                cur.execute(
                    """
                    INSERT INTO transactions
                        (reference, description, amount, transaction_type, category,
                         account_id, customer_id, invoice_id, tags, metadata)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id, date, reference, description, amount, transaction_type,
                              category, account_id, customer_id, invoice_id, status, tags, metadata, created_at
                    """,
                    (
                        data.get("reference"),
                        description,
                        amount,
                        txn_type,
                        data.get("category"),
                        data.get("account_id"),
                        data.get("customer_id"),
                        data.get("invoice_id"),
                        Json(data.get("tags", [])),
                        Json(data.get("metadata", {})),
                    ),
                )
            txn = cur.fetchone()

        event_bus.emit(
            "transaction.created",
            {
                "transaction_id": txn["id"],
                "amount": float(txn["amount"]),
                "transaction_type": txn["transaction_type"],
                "description": txn["description"],
            },
            tenant_id=g.tenant_id,
        )
        return jsonify(txn), 201

    @bp.route("/api/transactions/<int:txn_id>", methods=["GET"])
    @login_required
    @require_module("accounting")
    def get_transaction(txn_id):
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                SELECT id, date, reference, description, amount, transaction_type,
                       category, account_id, customer_id, invoice_id, status, tags, metadata, created_at
                FROM transactions WHERE id = %s
                """,
                (txn_id,),
            )
            txn = cur.fetchone()

        if txn is None:
            return jsonify({"error": "transaction not found"}), 404
        return jsonify(txn)

    @bp.route("/api/transactions/<int:txn_id>", methods=["PUT"])
    @login_required
    @require_module("accounting")
    def update_transaction(txn_id):
        data = request.get_json(force=True)
        sets = []
        params = []

        for field in ("date", "reference", "description", "category"):
            if field in data:
                sets.append(f"{field} = %s")
                params.append(data[field])
        if "amount" in data:
            sets.append("amount = %s")
            params.append(float(data["amount"]))
        if "account_id" in data:
            sets.append("account_id = %s")
            params.append(data["account_id"])
        if "tags" in data:
            sets.append("tags = %s")
            params.append(Json(data["tags"]))
        if "metadata" in data:
            sets.append("metadata = %s")
            params.append(Json(data["metadata"]))

        if not sets:
            return jsonify({"error": "no fields to update"}), 400

        params.append(txn_id)

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                f"""
                UPDATE transactions SET {', '.join(sets)}
                WHERE id = %s AND status != 'voided'
                RETURNING id, date, reference, description, amount, transaction_type,
                          category, account_id, customer_id, invoice_id, status, tags, metadata, created_at
                """,
                params,
            )
            txn = cur.fetchone()

        if txn is None:
            return jsonify({"error": "transaction not found or already voided"}), 404
        return jsonify(txn)

    @bp.route("/api/transactions/<int:txn_id>/void", methods=["POST"])
    @login_required
    @require_module("accounting")
    def void_transaction(txn_id):
        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                UPDATE transactions SET status = 'voided'
                WHERE id = %s AND status != 'voided'
                RETURNING id, status
                """,
                (txn_id,),
            )
            result = cur.fetchone()

        if result is None:
            return jsonify({"error": "transaction not found or already voided"}), 404
        return jsonify({"voided": True, "id": result["id"]})

    # ------------------------------------------------------------------
    # Expenses
    # ------------------------------------------------------------------

    @bp.route("/api/expenses", methods=["GET"])
    @login_required
    @require_module("accounting")
    def list_expenses():
        page = request.args.get("page", 1, type=int)
        per_page = request.args.get("per_page", 25, type=int)
        offset = (page - 1) * per_page
        start_date = request.args.get("start_date")
        end_date = request.args.get("end_date")
        vendor = request.args.get("vendor")
        category = request.args.get("category")
        status = request.args.get("status")

        where_clauses = []
        params: list = []

        if start_date:
            where_clauses.append("date >= %s")
            params.append(start_date)
        if end_date:
            where_clauses.append("date <= %s")
            params.append(end_date)
        if vendor:
            where_clauses.append("vendor ILIKE %s")
            params.append(f"%{vendor}%")
        if category:
            where_clauses.append("category = %s")
            params.append(category)
        if status:
            where_clauses.append("status = %s")
            params.append(status)

        where = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(f"SELECT COUNT(*) AS cnt FROM expenses {where}", params)
            total = cur.fetchone()["cnt"]
            cur.execute(
                f"""
                SELECT id, date, vendor, description, amount, category, account_id,
                       payment_method, receipt_url, is_billable, customer_id, status, tags, created_at
                FROM expenses {where}
                ORDER BY date DESC, id DESC
                LIMIT %s OFFSET %s
                """,
                params + [per_page, offset],
            )
            expenses = cur.fetchall()

        return jsonify({"expenses": expenses, "total": total, "page": page, "per_page": per_page})

    @bp.route("/api/expenses", methods=["POST"])
    @login_required
    @require_module("accounting")
    def create_expense():
        data = request.get_json(force=True)
        vendor = (data.get("vendor") or "").strip()

        if not vendor:
            return jsonify({"error": "vendor is required"}), 400

        try:
            amount = float(data.get("amount", 0))
        except (TypeError, ValueError):
            return jsonify({"error": "amount must be a number"}), 400

        if amount <= 0:
            return jsonify({"error": "amount must be greater than zero"}), 400

        exp_date = data.get("date") or None
        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            if exp_date:
                cur.execute(
                    """
                    INSERT INTO expenses
                        (date, vendor, description, amount, category, account_id,
                         payment_method, receipt_url, is_billable, customer_id, tags, metadata)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id, date, vendor, description, amount, category, account_id,
                              payment_method, receipt_url, is_billable, customer_id, status, tags, metadata, created_at
                    """,
                    (
                        exp_date,
                        vendor,
                        data.get("description"),
                        amount,
                        data.get("category"),
                        data.get("account_id"),
                        data.get("payment_method"),
                        data.get("receipt_url"),
                        bool(data.get("is_billable", False)),
                        data.get("customer_id"),
                        Json(data.get("tags", [])),
                        Json(data.get("metadata", {})),
                    ),
                )
            else:
                cur.execute(
                    """
                    INSERT INTO expenses
                        (vendor, description, amount, category, account_id,
                         payment_method, receipt_url, is_billable, customer_id, tags, metadata)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id, date, vendor, description, amount, category, account_id,
                              payment_method, receipt_url, is_billable, customer_id, status, tags, metadata, created_at
                    """,
                    (
                        vendor,
                        data.get("description"),
                        amount,
                        data.get("category"),
                        data.get("account_id"),
                        data.get("payment_method"),
                        data.get("receipt_url"),
                        bool(data.get("is_billable", False)),
                        data.get("customer_id"),
                        Json(data.get("tags", [])),
                        Json(data.get("metadata", {})),
                    ),
                )
            expense = cur.fetchone()

        event_bus.emit(
            "expense.recorded",
            {
                "expense_id": expense["id"],
                "vendor": expense["vendor"],
                "amount": float(expense["amount"]),
                "category": expense["category"],
            },
            tenant_id=g.tenant_id,
        )
        return jsonify(expense), 201

    @bp.route("/api/expenses/<int:expense_id>", methods=["GET"])
    @login_required
    @require_module("accounting")
    def get_expense(expense_id):
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                SELECT id, date, vendor, description, amount, category, account_id,
                       payment_method, receipt_url, is_billable, customer_id, status, tags, metadata, created_at
                FROM expenses WHERE id = %s
                """,
                (expense_id,),
            )
            expense = cur.fetchone()

        if expense is None:
            return jsonify({"error": "expense not found"}), 404
        return jsonify(expense)

    @bp.route("/api/expenses/<int:expense_id>", methods=["PUT"])
    @login_required
    @require_module("accounting")
    def update_expense(expense_id):
        data = request.get_json(force=True)
        sets = []
        params = []

        for field in ("date", "vendor", "description", "category", "payment_method", "receipt_url"):
            if field in data:
                sets.append(f"{field} = %s")
                params.append(data[field])
        if "amount" in data:
            sets.append("amount = %s")
            params.append(float(data["amount"]))
        if "is_billable" in data:
            sets.append("is_billable = %s")
            params.append(bool(data["is_billable"]))
        if "account_id" in data:
            sets.append("account_id = %s")
            params.append(data["account_id"])
        if "tags" in data:
            sets.append("tags = %s")
            params.append(Json(data["tags"]))

        if not sets:
            return jsonify({"error": "no fields to update"}), 400

        params.append(expense_id)

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                f"""
                UPDATE expenses SET {', '.join(sets)}
                WHERE id = %s
                RETURNING id, date, vendor, description, amount, category, account_id,
                          payment_method, receipt_url, is_billable, customer_id, status, tags, metadata, created_at
                """,
                params,
            )
            expense = cur.fetchone()

        if expense is None:
            return jsonify({"error": "expense not found"}), 404
        return jsonify(expense)

    @bp.route("/api/expenses/<int:expense_id>/approve", methods=["POST"])
    @login_required
    @require_module("accounting")
    def approve_expense(expense_id):
        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                UPDATE expenses SET status = 'approved'
                WHERE id = %s AND status = 'pending'
                RETURNING id, status, vendor, amount
                """,
                (expense_id,),
            )
            result = cur.fetchone()

        if result is None:
            return jsonify({"error": "expense not found or not in pending status"}), 404
        return jsonify(result)

    # ------------------------------------------------------------------
    # Tax Rates
    # ------------------------------------------------------------------

    @bp.route("/api/tax-rates", methods=["GET"])
    @login_required
    @require_module("accounting")
    def list_tax_rates():
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                "SELECT id, name, rate, description, is_default, is_active, created_at FROM tax_rates ORDER BY name"
            )
            rates = cur.fetchall()
        return jsonify({"tax_rates": rates})

    @bp.route("/api/tax-rates", methods=["POST"])
    @login_required
    @require_module("accounting")
    def create_tax_rate():
        data = request.get_json(force=True)
        name = (data.get("name") or "").strip()
        if not name:
            return jsonify({"error": "name is required"}), 400
        try:
            rate = float(data.get("rate", 0))
        except (TypeError, ValueError):
            return jsonify({"error": "rate must be a number"}), 400

        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                INSERT INTO tax_rates (name, rate, description, is_default, is_active)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id, name, rate, description, is_default, is_active, created_at
                """,
                (
                    name,
                    rate,
                    data.get("description"),
                    bool(data.get("is_default", False)),
                    bool(data.get("is_active", True)),
                ),
            )
            tax_rate = cur.fetchone()

        return jsonify(tax_rate), 201

    # ------------------------------------------------------------------
    # Reports
    # ------------------------------------------------------------------

    @bp.route("/api/reports/profit-loss", methods=["GET"])
    @login_required
    @require_module("accounting")
    def report_profit_loss():
        start_date = request.args.get("start_date")
        end_date = request.args.get("end_date")

        date_filter = ""
        params: list = []
        if start_date:
            date_filter += " AND t.date >= %s"
            params.append(start_date)
        if end_date:
            date_filter += " AND t.date <= %s"
            params.append(end_date)

        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)

            # Revenue: income transactions
            cur.execute(
                f"""
                SELECT COALESCE(SUM(amount), 0) AS total
                FROM transactions
                WHERE transaction_type = 'income' AND status != 'voided' {date_filter}
                """,
                params,
            )
            revenue = float(cur.fetchone()["total"])

            # Expenses: expense transactions + approved/paid expenses
            cur.execute(
                f"""
                SELECT COALESCE(SUM(amount), 0) AS total
                FROM transactions
                WHERE transaction_type = 'expense' AND status != 'voided' {date_filter}
                """,
                params,
            )
            expense_txns = float(cur.fetchone()["total"])

            # Also sum approved/paid expenses table
            exp_date_filter = date_filter.replace("t.date", "date")
            exp_params = params[:]
            cur.execute(
                f"""
                SELECT COALESCE(SUM(amount), 0) AS total
                FROM expenses
                WHERE status IN ('approved', 'paid') {exp_date_filter}
                """,
                exp_params,
            )
            expense_records = float(cur.fetchone()["total"])

            # Revenue by account
            cur.execute(
                f"""
                SELECT a.code, a.name, COALESCE(SUM(t.amount), 0) AS total
                FROM transactions t
                JOIN chart_of_accounts a ON a.id = t.account_id
                WHERE t.transaction_type = 'income' AND t.status != 'voided' {date_filter}
                GROUP BY a.id, a.code, a.name
                ORDER BY a.code
                """,
                params,
            )
            revenue_by_account = cur.fetchall()

            # Expenses by category
            cur.execute(
                f"""
                SELECT COALESCE(category, 'Uncategorized') AS category,
                       COALESCE(SUM(amount), 0) AS total
                FROM transactions
                WHERE transaction_type = 'expense' AND status != 'voided' {date_filter}
                GROUP BY category
                ORDER BY total DESC
                """,
                params,
            )
            expenses_by_category = cur.fetchall()

        total_expenses = expense_txns + expense_records
        net_income = revenue - total_expenses

        event_bus.emit(
            "report.generated",
            {"report_type": "profit_loss", "net_income": net_income},
            tenant_id=g.tenant_id,
        )

        return jsonify(
            {
                "period": {"start_date": start_date, "end_date": end_date},
                "revenue": revenue,
                "expenses": total_expenses,
                "net_income": net_income,
                "revenue_by_account": revenue_by_account,
                "expenses_by_category": expenses_by_category,
            }
        )

    @bp.route("/api/reports/balance-sheet", methods=["GET"])
    @login_required
    @require_module("accounting")
    def report_balance_sheet():
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                """
                SELECT account_type,
                       COALESCE(SUM(balance), 0) AS total,
                       json_agg(json_build_object('code', code, 'name', name, 'balance', balance)
                                ORDER BY code) AS accounts
                FROM chart_of_accounts
                WHERE is_active = true
                GROUP BY account_type
                """
            )
            rows = cur.fetchall()

        totals = {r["account_type"]: {"total": float(r["total"]), "accounts": r["accounts"]} for r in rows}

        assets = totals.get("asset", {}).get("total", 0)
        liabilities = totals.get("liability", {}).get("total", 0)
        equity = totals.get("equity", {}).get("total", 0)

        return jsonify(
            {
                "assets": totals.get("asset", {"total": 0, "accounts": []}),
                "liabilities": totals.get("liability", {"total": 0, "accounts": []}),
                "equity": totals.get("equity", {"total": 0, "accounts": []}),
                "total_assets": assets,
                "total_liabilities": liabilities,
                "total_equity": equity,
                "balance_check": assets - (liabilities + equity),
            }
        )

    @bp.route("/api/reports/expense-summary", methods=["GET"])
    @login_required
    @require_module("accounting")
    def report_expense_summary():
        start_date = request.args.get("start_date")
        end_date = request.args.get("end_date")

        where_clauses = ["status IN ('approved', 'paid')"]
        params: list = []
        if start_date:
            where_clauses.append("date >= %s")
            params.append(start_date)
        if end_date:
            where_clauses.append("date <= %s")
            params.append(end_date)

        where = "WHERE " + " AND ".join(where_clauses)

        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)
            cur.execute(
                f"""
                SELECT COALESCE(category, 'Uncategorized') AS category,
                       COUNT(*) AS count,
                       COALESCE(SUM(amount), 0) AS total
                FROM expenses {where}
                GROUP BY category
                ORDER BY total DESC
                """,
                params,
            )
            by_category = cur.fetchall()

            cur.execute(
                f"SELECT COALESCE(SUM(amount), 0) AS grand_total FROM expenses {where}", params
            )
            grand_total = float(cur.fetchone()["grand_total"])

        return jsonify(
            {
                "period": {"start_date": start_date, "end_date": end_date},
                "grand_total": grand_total,
                "by_category": by_category,
            }
        )

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    @bp.route("/api/stats", methods=["GET"])
    @login_required
    @require_module("accounting")
    def stats():
        with get_db_cursor(commit=False, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, g.tenant_id)

            # Revenue this month
            cur.execute(
                """
                SELECT COALESCE(SUM(amount), 0) AS total
                FROM transactions
                WHERE transaction_type = 'income'
                  AND status != 'voided'
                  AND date >= date_trunc('month', CURRENT_DATE)
                """
            )
            revenue_this_month = float(cur.fetchone()["total"])

            # Expenses this month (transaction-based)
            cur.execute(
                """
                SELECT COALESCE(SUM(amount), 0) AS total
                FROM transactions
                WHERE transaction_type = 'expense'
                  AND status != 'voided'
                  AND date >= date_trunc('month', CURRENT_DATE)
                """
            )
            expense_txns_month = float(cur.fetchone()["total"])

            # Expenses this month (expense records)
            cur.execute(
                """
                SELECT COALESCE(SUM(amount), 0) AS total
                FROM expenses
                WHERE status IN ('approved', 'paid')
                  AND date >= date_trunc('month', CURRENT_DATE)
                """
            )
            expense_records_month = float(cur.fetchone()["total"])

            # Account count
            cur.execute("SELECT COUNT(*) AS cnt FROM chart_of_accounts WHERE is_active = true")
            account_count = cur.fetchone()["cnt"]

        total_expenses = expense_txns_month + expense_records_month
        net_income = revenue_this_month - total_expenses

        return jsonify(
            {
                "revenue_this_month": revenue_this_month,
                "expenses_this_month": total_expenses,
                "net_income": net_income,
                "account_count": account_count,
            }
        )


# ------------------------------------------------------------------
# Event consumers (module-level, not route handlers)
# ------------------------------------------------------------------


def on_invoice_paid(data):
    """Auto-record an income transaction when an invoice is paid."""
    tenant_id = data.get("_tenant_id")
    invoice_id = data.get("invoice_id")
    amount = data.get("amount") or data.get("total")
    if not tenant_id or not amount:
        return
    try:
        with get_db_cursor(commit=True, dict_cursor=True) as (conn, cur):
            set_tenant_search_path(cur, tenant_id)
            # Find Sales Revenue account (code 4000)
            cur.execute(
                "SELECT id FROM chart_of_accounts WHERE code = '4000' AND is_active = true LIMIT 1"
            )
            row = cur.fetchone()
            account_id = row["id"] if row else None

            cur.execute(
                """
                INSERT INTO transactions
                    (description, amount, transaction_type, category, account_id,
                     customer_id, invoice_id, metadata)
                VALUES (%s, %s, 'income', 'Sales Revenue', %s, %s, %s, %s)
                """,
                (
                    data.get("description", f"Invoice #{invoice_id} payment received"),
                    float(amount),
                    account_id,
                    data.get("customer_id"),
                    invoice_id,
                    Json({"source": "event_bus", "event": "invoice.paid"}),
                ),
            )
    except Exception:
        logger.exception("Failed to record income transaction for invoice %s", invoice_id)


def on_payment_received(data):
    """Placeholder — acknowledge payment.received events."""
    logger.debug(
        "accounting: payment.received event for tenant %s (no-op)", data.get("_tenant_id")
    )

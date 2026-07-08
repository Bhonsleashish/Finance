"""Finance OS command-line interface.

Everything runs locally against database/finance.db. Run `finance --help`
(after `pip install -e .`) or `python -m finance_os.cli.main --help`.
"""

from __future__ import annotations

import json
from enum import Enum
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from finance_os.categorize.categorizer import Categorizer
from finance_os.config import load_settings
from finance_os.db.connection import connect, ensure_initialized
from finance_os.ingest.ingest_pipeline import ingest_path
from finance_os.utils.dates import current_period_month


class DocType(str, Enum):
    payslip = "payslip"
    bank_statement = "bank_statement"
    csv_export = "csv_export"
    receipt = "receipt"
    invoice = "invoice"
    insurance = "insurance"
    tax = "tax"
    investment = "investment"
    screenshot = "screenshot"

app = typer.Typer(add_completion=False, help="Finance OS — your offline personal finance operating system.")
console = Console()

goals_app = typer.Typer(help="Manage financial goals.")
app.add_typer(goals_app, name="goals")

budget_app = typer.Typer(help="Adaptive budgeting.")
app.add_typer(budget_app, name="budget")

report_app = typer.Typer(help="Generate reviews and exports.")
app.add_typer(report_app, name="report")

expense_app = typer.Typer(help="Manually add, list or delete transactions.")
app.add_typer(expense_app, name="expense")

investment_app = typer.Typer(help="Track investments/holdings.")
app.add_typer(investment_app, name="investment")

auth_app = typer.Typer(help="Manage the dashboard's local login password.")
app.add_typer(auth_app, name="auth")


@app.command()
def init() -> None:
    """Initialize the local database and seed categories/merchants."""
    path = ensure_initialized()
    console.print(f"[green]Database ready at {path}[/green]")


@app.command()
def ingest(
    path: Path = typer.Argument(..., help="File or folder to ingest (e.g. data/inbox, or a single PDF/CSV)."),
    type_: Optional[DocType] = typer.Option(
        None, "--type",
        help="Force the document type instead of auto-detecting (e.g. a payslip that isn't in data/salary_slips/). "
             "Only valid when `path` is a single file, not a folder.",
    ),
) -> None:
    """Ingest payslips, bank statements, receipts, CSVs. Safe to re-run — duplicates are skipped."""
    with connect() as conn:
        from finance_os.db.connection import init_db
        init_db(conn)
        categorizer = Categorizer(conn)
        try:
            results = ingest_path(conn, path, categorizer, doc_type=type_.value if type_ else None)
        except ValueError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1)

    table = Table(title=f"Ingestion results: {path}")
    table.add_column("File")
    table.add_column("Type")
    table.add_column("Status")
    table.add_column("Transactions")
    table.add_column("Message")
    for r in results:
        color = {"imported": "green", "duplicate": "yellow", "needs_review": "orange3", "failed": "red"}.get(r.status, "white")
        table.add_row(r.file.name, r.doc_type, f"[{color}]{r.status}[/{color}]", str(r.transactions_added), r.message)
    console.print(table)
    if not results:
        console.print("[yellow]No supported files found.[/yellow]")


@app.command()
def categorize(transaction_id: int, category: str) -> None:
    """Manually correct a transaction's category. The system learns from this."""
    with connect() as conn:
        from finance_os.db.connection import init_db
        init_db(conn)
        row = conn.execute("SELECT description_raw FROM transactions WHERE id = ?", (transaction_id,)).fetchone()
        if not row:
            console.print(f"[red]No transaction with id {transaction_id}[/red]")
            raise typer.Exit(1)
        categorizer = Categorizer(conn)
        categorizer.learn_correction(transaction_id, row["description_raw"], category)
    console.print(f"[green]Transaction {transaction_id} recategorized as '{category}' — pattern learned.[/green]")


@app.command()
def uncategorized() -> None:
    """List transactions that still need a category."""
    with connect() as conn:
        from finance_os.db.connection import init_db
        init_db(conn)
        from finance_os.db import repository as repo
        df = repo.uncategorized_transactions(conn)
    if df.empty:
        console.print("[green]Nothing to review — everything is categorized.[/green]")
        return
    table = Table(title="Uncategorized transactions")
    table.add_column("ID")
    table.add_column("Date")
    table.add_column("Description")
    table.add_column("Amount")
    for _, row in df.iterrows():
        table.add_row(str(row["id"]), row["txn_date"], row["description_raw"], f"{row['amount']:,.2f}")
    console.print(table)


@expense_app.command("add")
def expense_add(
    description: str,
    amount: float = typer.Option(..., help="Positive for income, negative for an expense."),
    date_: str = typer.Option(..., "--date", help="YYYY-MM-DD"),
    category: str = typer.Option(None, help="Leave blank to auto-categorize."),
    account: str = typer.Option("manual", help="Account name, e.g. 'Sparkasse Girokonto'."),
) -> None:
    """Manually record an expense or income transaction."""
    from finance_os.db import repository as repo

    with connect() as conn:
        from finance_os.db.connection import init_db
        init_db(conn)
        categorizer = Categorizer(conn)
        if category:
            category_id = repo.get_or_create_category(conn, category)
            merchant_id = None
        else:
            result = categorizer.categorize(description)
            category_id, merchant_id = result.category_id, result.merchant_id
        account_id = repo.get_or_create_account(conn, account)
        direction = "income" if amount > 0 else "expense"
        txn_id = repo.insert_transaction(
            conn, txn_date=date_, description_raw=description, amount=amount, direction=direction,
            account_id=account_id, category_id=category_id, merchant_id=merchant_id,
            is_manual_entry=True, account_name=account,
        )
    if txn_id is None:
        console.print("[yellow]Skipped — an identical transaction already exists (same date/amount/description/account).[/yellow]")
    else:
        console.print(f"[green]Added transaction {txn_id}: {description} ({amount:,.2f} EUR)[/green]")


@expense_app.command("delete")
def expense_delete(transaction_id: int) -> None:
    """Delete a transaction by id."""
    from finance_os.db import repository as repo

    with connect() as conn:
        from finance_os.db.connection import init_db
        init_db(conn)
        deleted = repo.delete_transaction(conn, transaction_id)
    if deleted:
        console.print(f"[green]Deleted transaction {transaction_id}.[/green]")
    else:
        console.print(f"[red]No transaction with id {transaction_id}[/red]")
        raise typer.Exit(1)


@expense_app.command("list")
def expense_list(month: str = typer.Option(None, help="YYYY-MM, defaults to all history")) -> None:
    """List transactions (optionally filtered to one month)."""
    from finance_os.db import repository as repo

    with connect() as conn:
        from finance_os.db.connection import init_db
        init_db(conn)
        df = repo.get_transactions_df(conn, month, month)
    if df.empty:
        console.print("[yellow]No transactions found.[/yellow]")
        return
    df = df.copy()
    df["txn_date"] = df["txn_date"].dt.strftime("%Y-%m-%d")
    table = Table(title="Transactions")
    for col in ("id", "txn_date", "description_raw", "merchant", "category", "amount", "account"):
        table.add_column(col)
    for _, row in df.iterrows():
        table.add_row(*(str(row[c])[:40] for c in ("id", "txn_date", "description_raw", "merchant", "category", "amount", "account")))
    console.print(table)


@app.command()
def income(month: str = typer.Option(current_period_month(), help="YYYY-MM")) -> None:
    """Estimate total income for a month (confirmed so far + projected remainder)."""
    from finance_os.analysis.salary import estimate_month_income

    with connect() as conn:
        from finance_os.db.connection import init_db
        init_db(conn)
        est = estimate_month_income(conn, month)

    console.print(f"\n[bold]Estimated income for {month}[/bold]  (basis: {est.basis})\n")
    console.print(f"  Received so far:    EUR {est.received_so_far:,.2f}")
    console.print(f"  Remaining expected: EUR {est.remaining_expected:,.2f}")
    console.print(f"  [bold]Estimated total:    EUR {est.estimated_total:,.2f}[/bold]")


@goals_app.command("delete")
def goals_delete(name: str) -> None:
    """Deactivate a goal (kept in history, hidden from lists/dashboard)."""
    from finance_os.db import repository as repo

    with connect() as conn:
        from finance_os.db.connection import init_db
        init_db(conn)
        goals = repo.list_goals(conn)
        row = goals[goals["name"] == name]
        if row.empty:
            console.print(f"[red]No active goal named '{name}'[/red]")
            raise typer.Exit(1)
        repo.deactivate_goal(conn, int(row.iloc[0]["id"]))
    console.print(f"[green]Goal '{name}' deleted.[/green]")


@investment_app.command("add")
def investment_add(
    name: str,
    amount: float = typer.Option(..., help="Amount invested (cost basis, EUR)."),
    date_: str = typer.Option(..., "--date", help="Purchase date, YYYY-MM-DD"),
    asset_type: str = typer.Option("other", help="stock | etf | crypto | fund | bond | other"),
    broker: str = typer.Option(None),
    quantity: float = typer.Option(None, help="Number of shares/coins, if known."),
    current_value: float = typer.Option(None, help="Current value, if known (defaults to cost basis)."),
) -> None:
    """Record an investment purchase."""
    from finance_os.db import repository as repo

    with connect() as conn:
        from finance_os.db.connection import init_db
        init_db(conn)
        inv_id = repo.add_investment(
            conn, name, date_, amount, asset_type=asset_type, broker=broker,
            quantity=quantity, current_value=current_value,
        )
    console.print(f"[green]Recorded investment {inv_id}: {name} — EUR {amount:,.2f} on {date_}[/green]")


@investment_app.command("list")
def investment_list() -> None:
    """Show all holdings with cost basis, current value and unrealized gain/loss."""
    from finance_os.analysis.investments import holdings_df, portfolio_summary

    with connect() as conn:
        from finance_os.db.connection import init_db
        init_db(conn)
        df = holdings_df(conn)
        summary = portfolio_summary(conn)

    if df.empty:
        console.print("[yellow]No investments recorded yet. Use `finance investment add`.[/yellow]")
        return

    table = Table(title="Holdings")
    for col in ("id", "name", "asset_type", "purchase_date", "amount_invested", "effective_value", "unrealized_gain"):
        table.add_column(col)
    for _, row in df.iterrows():
        marker = " (est.)" if row["value_is_estimated"] else ""
        table.add_row(
            str(row["id"]), row["name"], row["asset_type"], row["purchase_date"],
            f"{row['amount_invested']:,.2f}", f"{row['effective_value']:,.2f}{marker}",
            f"{row['unrealized_gain']:+,.2f}",
        )
    console.print(table)
    gain_pct = f"{summary.unrealized_gain_pct:+.1%}" if summary.unrealized_gain_pct is not None else "n/a"
    console.print(
        f"\nTotal invested: EUR {summary.total_invested:,.2f}  |  "
        f"Current value: EUR {summary.total_current_value:,.2f}  |  "
        f"Unrealized: EUR {summary.unrealized_gain:+,.2f} ({gain_pct})"
    )
    if summary.stale_value_count:
        console.print(f"[yellow]{summary.stale_value_count} holding(s) still valued at cost — "
                       f"update with `finance investment update-value <id> <current_value>`.[/yellow]")


@investment_app.command("update-value")
def investment_update_value(investment_id: int, current_value: float) -> None:
    """Update a holding's current market value."""
    from finance_os.db import repository as repo

    with connect() as conn:
        from finance_os.db.connection import init_db
        init_db(conn)
        updated = repo.update_investment_value(conn, investment_id, current_value)
    if updated:
        console.print(f"[green]Updated investment {investment_id} to EUR {current_value:,.2f}.[/green]")
    else:
        console.print(f"[red]No investment with id {investment_id}[/red]")
        raise typer.Exit(1)


@investment_app.command("delete")
def investment_delete(investment_id: int) -> None:
    """Delete an investment record."""
    from finance_os.db import repository as repo

    with connect() as conn:
        from finance_os.db.connection import init_db
        init_db(conn)
        deleted = repo.delete_investment(conn, investment_id)
    if deleted:
        console.print(f"[green]Deleted investment {investment_id}.[/green]")
    else:
        console.print(f"[red]No investment with id {investment_id}[/red]")
        raise typer.Exit(1)


@budget_app.command("generate")
def budget_generate(month: str = typer.Option(current_period_month(), help="YYYY-MM")) -> None:
    """Generate (and persist) the adaptive budget for a month."""
    from finance_os.analysis.budgeting import generate_budget, persist_budget

    with connect() as conn:
        from finance_os.db.connection import init_db
        init_db(conn)
        lines = generate_budget(conn, month)
        persist_budget(conn, month, lines)

    table = Table(title=f"Adaptive budget: {month}")
    table.add_column("Category")
    table.add_column("Group")
    table.add_column("Budget (EUR)")
    table.add_column("Basis")
    for line in lines:
        table.add_row(line.category, line.group, f"{line.budgeted_amount:,.2f}", line.basis)
    console.print(table)


@budget_app.command("status")
def budget_status(month: str = typer.Option(current_period_month(), help="YYYY-MM")) -> None:
    """Show budget vs. actual for a month."""
    from finance_os.analysis.budgeting import budget_vs_actual

    with connect() as conn:
        from finance_os.db.connection import init_db
        init_db(conn)
        df = budget_vs_actual(conn, month)
    if df.empty:
        console.print("[yellow]No budget or transactions found for this month yet.[/yellow]")
        return
    table = Table(title=f"Budget vs actual: {month}")
    table.add_column("Category")
    table.add_column("Budgeted")
    table.add_column("Actual")
    table.add_column("Variance")
    table.add_column("% Used")
    for _, row in df.iterrows():
        pct = f"{row['pct_used']:.0%}" if row["pct_used"] is not None else "n/a"
        table.add_row(row["category"], f"{row['budgeted_amount']:,.2f}", f"{row['actual']:,.2f}", f"{row['variance']:,.2f}", pct)
    console.print(table)


@goals_app.command("add")
def goals_add(
    name: str,
    goal_type: str = typer.Option("custom"),
    target_amount: float = typer.Option(...),
    current_amount: float = typer.Option(0.0),
    monthly_contribution: float = typer.Option(0.0),
    target_date: str = typer.Option(None),
) -> None:
    """Create or update a goal."""
    from finance_os.analysis.goals import create_or_update_goal

    with connect() as conn:
        from finance_os.db.connection import init_db
        init_db(conn)
        create_or_update_goal(conn, name, goal_type, target_amount, current_amount, monthly_contribution, target_date)
    console.print(f"[green]Goal '{name}' saved.[/green]")


@goals_app.command("list")
def goals_list() -> None:
    """Show progress + estimated completion date for every goal."""
    from finance_os.analysis.goals import all_goals_progress

    with connect() as conn:
        from finance_os.db.connection import init_db
        init_db(conn)
        goals = all_goals_progress(conn)
    table = Table(title="Goals")
    table.add_column("Name")
    table.add_column("Progress")
    table.add_column("Current / Target")
    table.add_column("Est. Completion")
    for g in goals:
        completion = g.estimated_completion_date.isoformat() if g.estimated_completion_date else "n/a"
        table.add_row(g.name, f"{g.progress_pct:.0%}", f"{g.current_amount:,.2f} / {g.target_amount:,.2f}", completion)
    console.print(table)


@app.command()
def advise(item: str, cost: float) -> None:
    """Ask: should I buy <item> for <cost> EUR?"""
    from finance_os.analysis.advisor import evaluate_purchase

    with connect() as conn:
        from finance_os.db.connection import init_db
        init_db(conn)
        evaluation = evaluate_purchase(conn, item, cost)

    color = {"Buy now": "green", "Wait": "yellow", "Avoid": "red"}[evaluation.recommendation]
    console.print(f"\n[bold {color}]{evaluation.recommendation}[/bold {color}]: {item} (EUR {cost:,.2f})\n")
    for reason in evaluation.reasons:
        console.print(f"  - {reason}")
    if evaluation.cheaper_alternative_hint:
        console.print(f"\n[cyan]{evaluation.cheaper_alternative_hint}[/cyan]")


@app.command()
def tips(month: str = typer.Option(current_period_month(), help="YYYY-MM")) -> None:
    """Money-management suggestions, ranked by priority (emergency fund -> debt -> savings rate -> ...)."""
    from finance_os.analysis.coaching import money_management_tips

    with connect() as conn:
        from finance_os.db.connection import init_db
        init_db(conn)
        for tip in money_management_tips(conn, month):
            console.print(f"\n[bold cyan]{tip.priority}. {tip.title}[/bold cyan]")
            console.print(f"   {tip.detail}")
    console.print()


@app.command()
def forecast(balance: float = typer.Option(0.0, help="Current bank balance (EUR)")) -> None:
    """Project balance and net worth over 1/3/6/12/60 months."""
    from finance_os.analysis.forecasting import full_trajectory_report

    with connect() as conn:
        from finance_os.db.connection import init_db
        init_db(conn)
        report = full_trajectory_report(conn, balance)

    console.print(f"Average monthly cash flow: EUR {report['avg_monthly_cashflow']:,.2f} "
                  f"(trend: {report['trend_slope_per_month']:+.2f}/mo)")
    table = Table(title="Balance projection")
    table.add_column("Horizon")
    table.add_column("Projected balance (EUR)")
    for horizon, value in report["balance_projection"].items():
        table.add_row(horizon, f"{value:,.2f}")
    console.print(table)


@report_app.command("weekly")
def report_weekly() -> None:
    """Generate this week's review."""
    from finance_os.reports.weekly_review import generate_weekly_review

    with connect() as conn:
        from finance_os.db.connection import init_db
        init_db(conn)
        payload = generate_weekly_review(conn)
    console.print_json(json.dumps(payload, default=str))


@report_app.command("monthly")
def report_monthly(
    month: str = typer.Option(current_period_month(), help="YYYY-MM"),
    export_pdf: bool = typer.Option(False, help="Also export a PDF to reports/monthly/"),
) -> None:
    """Generate the monthly review, optionally exporting a PDF."""
    from finance_os.reports.exporters import export_monthly_review_pdf
    from finance_os.reports.monthly_review import generate_monthly_review

    settings = load_settings()
    with connect() as conn:
        from finance_os.db.connection import init_db
        init_db(conn)
        payload = generate_monthly_review(conn, month)
    console.print_json(json.dumps(payload, default=str))
    if export_pdf:
        out_path = settings.reports_dir / "monthly" / f"{month}.pdf"
        export_monthly_review_pdf(payload, out_path)
        console.print(f"[green]PDF written to {out_path}[/green]")


@report_app.command("export")
def report_export(
    fmt: str = typer.Option("csv", help="csv | excel"),
    start_month: str = typer.Option(None),
    end_month: str = typer.Option(None),
) -> None:
    """Export the full transaction ledger."""
    from finance_os.reports.exporters import export_transactions_csv, export_transactions_excel

    settings = load_settings()
    with connect() as conn:
        from finance_os.db.connection import init_db
        init_db(conn)
        if fmt == "csv":
            path = settings.exports_dir / "transactions.csv"
            export_transactions_csv(conn, path, start_month, end_month)
        elif fmt == "excel":
            path = settings.exports_dir / "transactions.xlsx"
            export_transactions_excel(conn, path, start_month, end_month)
        else:
            console.print(f"[red]Unknown format: {fmt}[/red]")
            raise typer.Exit(1)
    console.print(f"[green]Exported to {path}[/green]")


@auth_app.command("set-password")
def auth_set_password() -> None:
    """Set (or change) the password required to open the dashboard."""
    from finance_os import auth

    password = typer.prompt("New dashboard password", hide_input=True)
    confirm = typer.prompt("Confirm password", hide_input=True)
    if password != confirm:
        console.print("[red]Passwords didn't match — nothing was changed.[/red]")
        raise typer.Exit(1)
    try:
        auth.set_password(password)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)
    console.print(f"[green]Password set. It's stored (salted + hashed) in {auth.SECRETS_PATH}, "
                   f"which is gitignored and never committed. The dashboard will now require it.[/green]")


@auth_app.command("status")
def auth_status() -> None:
    """Check whether a dashboard password is currently set."""
    from finance_os import auth

    if auth.is_password_set():
        console.print("[green]A dashboard password is set.[/green]")
    else:
        console.print("[yellow]No dashboard password is set — anyone who can reach the dashboard can use it. "
                       "Run `finance auth set-password` to set one.[/yellow]")


@auth_app.command("clear")
def auth_clear() -> None:
    """Remove the dashboard password (dashboard becomes unprotected again)."""
    from finance_os import auth

    confirm = typer.confirm("This removes password protection from the dashboard. Continue?")
    if not confirm:
        raise typer.Exit(0)
    if auth.clear_password():
        console.print("[green]Password removed.[/green]")
    else:
        console.print("[yellow]No password was set.[/yellow]")


def _guess_lan_ip() -> str:
    """Best-effort local network IP, for printing a phone-friendly URL.
    Uses a UDP socket "connect" purely to ask the OS which interface it
    would route through — this sends no packets anywhere (UDP connect() is
    a local kernel call), consistent with this app making no network calls."""
    import socket

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
        finally:
            s.close()
    except Exception:  # noqa: BLE001
        return "<your-computer's-LAN-IP>"


@app.command()
def dashboard(
    network: bool = typer.Option(
        False, "--network",
        help="Bind to 0.0.0.0 so devices on your local network (e.g. your phone) can reach it. "
             "There is no login on this dashboard — only use this on a network you trust.",
    ),
    port: int = typer.Option(8501, help="Port to serve on."),
) -> None:
    """Launch the local Streamlit dashboard."""
    import subprocess
    import sys

    from finance_os import auth

    if network and not auth.is_password_set():
        console.print("[red]Refusing to start with --network: no dashboard password is set.[/red]")
        console.print("Anyone who can reach this port would have full access to your financial data. "
                       "Set one first:\n\n  finance auth set-password\n")
        raise typer.Exit(1)

    dashboard_path = Path(__file__).resolve().parent.parent / "dashboard" / "app.py"
    cmd = [sys.executable, "-m", "streamlit", "run", str(dashboard_path), "--server.port", str(port)]

    if network:
        cmd += ["--server.address", "0.0.0.0"]
        lan_ip = _guess_lan_ip()
        console.print(f"[yellow]Serving on your local network — password login is required.[/yellow]")
        console.print(f"On your phone (same Wi-Fi), open: [bold]http://{lan_ip}:{port}[/bold]\n")
    else:
        if not auth.is_password_set():
            console.print("[yellow]No dashboard password set. Run `finance auth set-password` to add one "
                           "(recommended even for localhost-only use).[/yellow]")
        console.print(f"Serving on localhost only. Open: [bold]http://localhost:{port}[/bold]")
        console.print("Run with --network to also make it reachable from your phone on the same Wi-Fi.\n")

    subprocess.run(cmd)


if __name__ == "__main__":
    app()

"""Finance OS command-line interface.

Everything runs locally against database/finance.db. Run `finance --help`
(after `pip install -e .`) or `python -m finance_os.cli.main --help`.
"""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from finance_os.categorize.categorizer import Categorizer
from finance_os.config import load_settings
from finance_os.db.connection import connect, ensure_initialized
from finance_os.ingest.ingest_pipeline import ingest_path
from finance_os.utils.dates import current_period_month

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


@app.command()
def init() -> None:
    """Initialize the local database and seed categories/merchants."""
    path = ensure_initialized()
    console.print(f"[green]Database ready at {path}[/green]")


@app.command()
def ingest(
    path: Path = typer.Argument(..., help="File or folder to ingest (e.g. data/inbox, or a single PDF/CSV)."),
) -> None:
    """Ingest payslips, bank statements, receipts, CSVs. Safe to re-run — duplicates are skipped."""
    with connect() as conn:
        from finance_os.db.connection import init_db
        init_db(conn)
        categorizer = Categorizer(conn)
        results = ingest_path(conn, path, categorizer)

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


@app.command()
def dashboard() -> None:
    """Launch the local Streamlit dashboard."""
    import subprocess
    import sys

    dashboard_path = Path(__file__).resolve().parent.parent / "dashboard" / "app.py"
    subprocess.run([sys.executable, "-m", "streamlit", "run", str(dashboard_path)])


if __name__ == "__main__":
    app()

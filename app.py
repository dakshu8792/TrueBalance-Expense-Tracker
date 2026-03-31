from flask import Flask, render_template, request, redirect, session, send_file, flash
import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash
from openpyxl import Workbook
import io
import re
from datetime import date, datetime
import os

app = Flask(__name__)
app.secret_key = "expense_tracker_secret_2024"

DB_PATH = os.path.join(os.path.dirname(__file__), "expenses.db")

CATEGORIES = [
    ("Food",          "🍔", "#f97316"),
    ("Travel",        "✈️",  "#3b82f6"),
    ("Shopping",      "🛒", "#8b5cf6"),
    ("Bills",         "💡", "#ef4444"),
    ("Rent",          "🏠", "#6366f1"),
    ("Entertainment", "🎬", "#ec4899"),
    ("Health",        "💊", "#10b981"),
    ("Education",     "📚", "#f59e0b"),
    ("Other",         "📦", "#6b7280"),
]

CAT_NAMES = [c[0] for c in CATEGORIES]

# ----------------------
# DATABASE
# ----------------------
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL
    )""")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS expenses(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        date TEXT NOT NULL,
        category TEXT NOT NULL,
        amount REAL NOT NULL,
        description TEXT,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )""")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS income(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER UNIQUE NOT NULL,
        amount REAL DEFAULT 0
    )""")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS budgets(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        category TEXT NOT NULL,
        limit_amount REAL NOT NULL,
        UNIQUE(user_id, category)
    )""")

    conn.commit()
    conn.close()


# ----------------------
# AUTH HELPERS
# ----------------------
def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect("/login")
        return f(*args, **kwargs)
    return decorated


# ----------------------
# REGISTER
# ----------------------
@app.route("/register", methods=["GET", "POST"])
def register():
    error = None
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"]
        confirm  = request.form.get("confirm_password", "")

        if len(username) < 3:
            error = "Username must be at least 3 characters."
        elif len(password) < 6:
            error = "Password must be at least 6 characters."
        elif password != confirm:
            error = "Passwords do not match."
        else:
            hashed = generate_password_hash(password)
            conn = get_db()
            try:
                conn.execute(
                    "INSERT INTO users(username, password) VALUES (?, ?)",
                    (username, hashed)
                )
                conn.commit()
                conn.close()
                flash("Account created! Please log in.", "success")
                return redirect("/login")
            except sqlite3.IntegrityError:
                conn.close()
                error = "Username already taken."

    return render_template("register.html", error=error)


# ----------------------
# LOGIN
# ----------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"]

        conn = get_db()
        user = conn.execute(
            "SELECT * FROM users WHERE username=?", (username,)
        ).fetchone()
        conn.close()

        if user and check_password_hash(user["password"], password):
            session["user_id"]  = user["id"]
            session["username"] = user["username"]
            return redirect("/")
        else:
            error = "Invalid username or password."

    return render_template("login.html", error=error)


# ----------------------
# LOGOUT
# ----------------------
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


# ----------------------
# DASHBOARD
# ----------------------
@app.route("/", methods=["GET"])
@login_required
def index():
    year     = request.args.get("year", "")
    month    = request.args.get("month", "")
    category = request.args.get("category", "")
    date_q   = request.args.get("date", "")

    conn   = get_db()
    uid    = session["user_id"]

    query  = "SELECT * FROM expenses WHERE user_id=?"
    params = [uid]

    if year:
        query += " AND strftime('%Y',date)=?"; params.append(year)
    if month:
        query += " AND strftime('%m',date)=?"; params.append(month)
    if category:
        query += " AND category=?"; params.append(category)
    if date_q:
        query += " AND date=?"; params.append(date_q)

    query += " ORDER BY date DESC"

    expenses = conn.execute(query, params).fetchall()
    total    = sum(e["amount"] for e in expenses) if expenses else 0

    # Income
    row    = conn.execute("SELECT amount FROM income WHERE user_id=?", (uid,)).fetchone()
    income = row["amount"] if row else 0
    balance = income - total

    # Monthly chart data
    monthly_data = conn.execute("""
        SELECT strftime('%m', date) as m, SUM(amount) as s
        FROM expenses WHERE user_id=?
        GROUP BY m ORDER BY m
    """, (uid,)).fetchall()
    months  = [r["m"] for r in monthly_data]
    amounts = [r["s"] for r in monthly_data]

    # Category breakdown (pie chart)
    cat_data = conn.execute("""
        SELECT category, SUM(amount) as s
        FROM expenses WHERE user_id=?
        GROUP BY category ORDER BY s DESC
    """, (uid,)).fetchall()
    cat_labels  = [r["category"] for r in cat_data]
    cat_amounts = [r["s"] for r in cat_data]

    # Top category
    top_category = cat_labels[0]  if cat_labels  else "None"
    top_amount   = cat_amounts[0] if cat_amounts else 0

    # This month vs last month
    today = datetime.today()
    this_m = today.strftime("%m"); this_y = today.strftime("%Y")
    last_m = f"{int(this_m)-1:02d}" if int(this_m) > 1 else "12"
    last_y = this_y if int(this_m) > 1 else str(int(this_y)-1)

    this_total = conn.execute(
        "SELECT COALESCE(SUM(amount),0) FROM expenses WHERE user_id=? AND strftime('%m',date)=? AND strftime('%Y',date)=?",
        (uid, this_m, this_y)
    ).fetchone()[0]
    last_total = conn.execute(
        "SELECT COALESCE(SUM(amount),0) FROM expenses WHERE user_id=? AND strftime('%m',date)=? AND strftime('%Y',date)=?",
        (uid, last_m, last_y)
    ).fetchone()[0]

    # Budgets
    budgets = {r["category"]: r["limit_amount"] for r in conn.execute(
        "SELECT category, limit_amount FROM budgets WHERE user_id=?", (uid,)
    ).fetchall()}

    # Category spend this month for budget alerts
    cat_this_month = {r["category"]: r["s"] for r in conn.execute("""
        SELECT category, SUM(amount) as s FROM expenses
        WHERE user_id=? AND strftime('%m',date)=? AND strftime('%Y',date)=?
        GROUP BY category
    """, (uid, this_m, this_y)).fetchall()}

    conn.close()

    budget_alerts = []
    for cat, limit in budgets.items():
        spent = cat_this_month.get(cat, 0)
        pct   = (spent / limit * 100) if limit > 0 else 0
        if pct >= 80:
            budget_alerts.append({
                "category": cat,
                "spent": spent,
                "limit": limit,
                "pct": round(pct, 1)
            })

    return render_template(
        "index.html",
        expenses=expenses,
        total=total,
        income=income,
        balance=balance,
        username=session["username"],
        months=months,
        amounts=amounts,
        cat_labels=cat_labels,
        cat_amounts=cat_amounts,
        top_category=top_category,
        top_amount=top_amount,
        this_total=this_total,
        last_total=last_total,
        budget_alerts=budget_alerts,
        categories=CATEGORIES,
        filters={"year": year, "month": month, "category": category, "date": date_q},
    )


# ----------------------
# ADD EXPENSE
# ----------------------
@app.route("/add", methods=["GET", "POST"])
@login_required
def add():
    if request.method == "POST":
        exp_date    = request.form["date"]
        category    = request.form["category"]
        amount      = float(request.form["amount"])
        description = request.form["description"].strip()

        conn = get_db()
        conn.execute(
            "INSERT INTO expenses(user_id, date, category, amount, description) VALUES (?,?,?,?,?)",
            (session["user_id"], exp_date, category, amount, description)
        )
        conn.commit()
        conn.close()
        flash("Expense added!", "success")
        return redirect("/")

    return render_template("add.html", categories=CATEGORIES, today=date.today().isoformat())


# ----------------------
# DELETE EXPENSE
# ----------------------
@app.route("/delete/<int:id>")
@login_required
def delete(id):
    conn = get_db()
    conn.execute(
        "DELETE FROM expenses WHERE id=? AND user_id=?",
        (id, session["user_id"])   # Prevent deleting other users' data
    )
    conn.commit()
    conn.close()
    flash("Expense deleted.", "info")
    return redirect("/")


# ----------------------
# EDIT EXPENSE
# ----------------------
@app.route("/edit/<int:id>", methods=["GET", "POST"])
@login_required
def edit(id):
    conn = get_db()

    if request.method == "POST":
        exp_date    = request.form["date"]
        category    = request.form["category"]
        amount      = float(request.form["amount"])
        description = request.form["description"].strip()

        conn.execute(
            "UPDATE expenses SET date=?, category=?, amount=?, description=? WHERE id=? AND user_id=?",
            (exp_date, category, amount, description, id, session["user_id"])
        )
        conn.commit()
        conn.close()
        flash("Expense updated!", "success")
        return redirect("/")

    expense = conn.execute(
        "SELECT * FROM expenses WHERE id=? AND user_id=?",
        (id, session["user_id"])
    ).fetchone()
    conn.close()

    if not expense:
        flash("Expense not found.", "danger")
        return redirect("/")

    return render_template("edit.html", expense=expense, categories=CATEGORIES)


# ----------------------
# EDIT INCOME
# ----------------------
@app.route("/edit_income", methods=["GET", "POST"])
@login_required
def edit_income():
    conn = get_db()
    uid  = session["user_id"]

    if request.method == "POST":
        amount = float(request.form["amount"])
        existing = conn.execute("SELECT id FROM income WHERE user_id=?", (uid,)).fetchone()
        if existing:
            conn.execute("UPDATE income SET amount=? WHERE user_id=?", (amount, uid))
        else:
            conn.execute("INSERT INTO income(user_id, amount) VALUES (?,?)", (uid, amount))
        conn.commit()
        conn.close()
        flash("Income updated!", "success")
        return redirect("/")

    row    = conn.execute("SELECT amount FROM income WHERE user_id=?", (uid,)).fetchone()
    income = row["amount"] if row else 0
    conn.close()

    return render_template("edit_income.html", income=income)


# ----------------------
# BUDGETS
# ----------------------
@app.route("/budgets", methods=["GET", "POST"])
@login_required
def budgets():
    conn = get_db()
    uid  = session["user_id"]

    if request.method == "POST":
        for cat in CAT_NAMES:
            val = request.form.get(f"budget_{cat}", "").strip()
            if val:
                conn.execute(
                    "INSERT INTO budgets(user_id, category, limit_amount) VALUES (?,?,?) "
                    "ON CONFLICT(user_id, category) DO UPDATE SET limit_amount=excluded.limit_amount",
                    (uid, cat, float(val))
                )
            else:
                conn.execute("DELETE FROM budgets WHERE user_id=? AND category=?", (uid, cat))
        conn.commit()
        conn.close()
        flash("Budgets saved!", "success")
        return redirect("/budgets")

    existing = {r["category"]: r["limit_amount"] for r in conn.execute(
        "SELECT category, limit_amount FROM budgets WHERE user_id=?", (uid,)
    ).fetchall()}
    conn.close()

    return render_template("budgets.html", categories=CATEGORIES, budgets=existing)


# ----------------------
# REPORTS
# ----------------------
@app.route("/reports")
@login_required
def reports():
    conn = get_db()
    uid  = session["user_id"]

    cat_data = conn.execute("""
        SELECT category, SUM(amount) as s FROM expenses
        WHERE user_id=? GROUP BY category ORDER BY s DESC
    """, (uid,)).fetchall()

    monthly_data = conn.execute("""
        SELECT strftime('%Y-%m', date) as ym, SUM(amount) as s
        FROM expenses WHERE user_id=? GROUP BY ym ORDER BY ym
    """, (uid,)).fetchall()

    conn.close()

    return render_template(
        "reports.html",
        categories=[r["category"] for r in cat_data],
        amounts=[r["s"] for r in cat_data],
        monthly_labels=[r["ym"] for r in monthly_data],
        monthly_amounts=[r["s"] for r in monthly_data],
    )


# ----------------------
# EXPORT EXCEL
# ----------------------
@app.route("/export_excel")
@login_required
def export_excel():
    conn = get_db()
    rows = conn.execute(
        "SELECT date, category, amount, description FROM expenses WHERE user_id=? ORDER BY date DESC",
        (session["user_id"],)
    ).fetchall()
    conn.close()

    wb = Workbook()
    ws = wb.active
    ws.title = "Expenses"
    ws.append(["Date", "Category", "Amount", "Description"])
    for r in rows:
        ws.append(list(r))

    file = io.BytesIO()
    wb.save(file)
    file.seek(0)

    return send_file(
        file,
        as_attachment=True,
        download_name=f"expenses_{date.today()}.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


# ----------------------
# SCAN RECEIPT (OCR)
# ----------------------
@app.route("/scan_receipt", methods=["GET", "POST"])
@login_required
def scan_receipt():
    result = None
    if request.method == "POST":
        uploaded = request.files.get("receipt")
        if not uploaded:
            flash("No file selected.", "danger")
            return redirect("/scan_receipt")

        try:
            import pytesseract
            import cv2
            import numpy as np
            from PIL import Image

            # Cross-platform: only set cmd if on Windows
            if os.name == "nt":
                tesseract_path = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
                if os.path.exists(tesseract_path):
                    pytesseract.pytesseract.tesseract_cmd = tesseract_path

            file_bytes = np.frombuffer(uploaded.read(), np.uint8)
            image = cv2.imdecode(file_bytes, cv2.IMREAD_COLOR)
            gray  = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            gray  = cv2.GaussianBlur(gray, (5, 5), 0)
            _, thresh = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY)

            text  = pytesseract.image_to_string(thresh)
            lines = [l.strip() for l in text.split("\n") if l.strip()]

            # Merchant name
            merchant = lines[0] if lines else "Unknown"

            # Amount
            amount = 0.0
            for line in lines:
                if any(k in line.lower() for k in ["total", "amount", "grand"]):
                    m = re.search(r'\d+\.?\d*', line)
                    if m:
                        amount = float(m.group())
                        break
            if amount == 0:
                nums = [float(n) for n in re.findall(r'\d+\.?\d*', text) if float(n) < 100000]
                if nums:
                    amount = max(nums)

            # Date
            detected_date = str(date.today())
            for pattern in [r'\d{2}/\d{2}/\d{4}', r'\d{2}-\d{2}-\d{4}', r'\d{4}-\d{2}-\d{2}']:
                m = re.search(pattern, text)
                if m:
                    detected_date = m.group()
                    break

            # Auto-categorise
            desc_lower = merchant.lower() + " " + text.lower()
            category = "Other"
            keyword_map = {
                "Food":          ["food", "restaurant", "swiggy", "zomato", "cafe", "pizza", "burger", "kfc", "mcd"],
                "Travel":        ["uber", "ola", "taxi", "fuel", "petrol", "flight", "bus", "train", "metro"],
                "Shopping":      ["amazon", "flipkart", "myntra", "mall", "store", "supermarket"],
                "Entertainment": ["netflix", "spotify", "cinema", "movie", "theatre", "concert"],
                "Bills":         ["electricity", "water", "internet", "wifi", "airtel", "jio", "bsnl"],
                "Health":        ["pharmacy", "hospital", "clinic", "medicine", "doctor", "apollo"],
            }
            for cat, keywords in keyword_map.items():
                if any(k in desc_lower for k in keywords):
                    category = cat
                    break

            result = {
                "merchant": merchant,
                "amount": amount,
                "date": detected_date,
                "category": category,
                "raw_text": text[:500],
            }

            # Auto-save
            conn = get_db()
            conn.execute(
                "INSERT INTO expenses(user_id, date, category, amount, description) VALUES(?,?,?,?,?)",
                (session["user_id"], detected_date, category, amount, merchant)
            )
            conn.commit()
            conn.close()
            flash("Receipt scanned and expense saved!", "success")
            return redirect("/")

        except ImportError:
            flash("OCR libraries not installed. Please install pytesseract, opencv-python, Pillow.", "danger")
        except Exception as e:
            flash(f"OCR error: {str(e)}", "danger")

    return render_template("scan_receipt.html", result=result)


# ----------------------
if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=10000)

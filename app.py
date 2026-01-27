from flask import Flask, render_template, request, redirect, session, flash, send_file
import sqlite3, csv
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
from fpdf import FPDF

app = Flask(__name__)
app.secret_key = "expense-tracker-secret"

def get_db():
    conn = sqlite3.connect("database.db")
    conn.row_factory = sqlite3.Row
    return conn

# ---------- LOGIN ----------
@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        db = get_db()
        user = db.execute(
            "SELECT * FROM users WHERE username=?",
            (request.form["username"],)
        ).fetchone()
        db.close()

        if user and check_password_hash(user["password"], request.form["password"]):
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session["role"] = user["role"]
            return redirect("/dashboard")
        flash("Invalid credentials")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

# ---------- DASHBOARD ----------
@app.route("/dashboard")
def dashboard():
    if "user_id" not in session:
        return redirect("/")

    db = get_db()

    # -------- TRANSACTIONS --------
    if session["role"] == "admin":
        transactions = db.execute("""
            SELECT t.*, u.username FROM transactions t
            JOIN users u ON t.user_id = u.id
            ORDER BY t.date DESC
        """).fetchall()
    else:
        transactions = db.execute("""
            SELECT * FROM transactions
            WHERE user_id = ?
            ORDER BY date DESC
        """, (session["user_id"],)).fetchall()

    user_filter = "" if session["role"] == "admin" else "AND user_id = ?"
    params = () if session["role"] == "admin" else (session["user_id"],)

    # -------- ANALYTICS (FIXED) --------
    daily = db.execute(f"""
        SELECT IFNULL(SUM(amount),0)
        FROM transactions
        WHERE date = DATE('now') {user_filter}
    """, params).fetchone()[0]

    weekly = db.execute(f"""
        SELECT IFNULL(SUM(amount),0)
        FROM transactions
        WHERE date >= DATE('now','-6 days') {user_filter}
    """, params).fetchone()[0]

    monthly = db.execute(f"""
        SELECT IFNULL(SUM(amount),0)
        FROM transactions
        WHERE strftime('%Y-%m', date) = strftime('%Y-%m','now')
        {user_filter}
    """, params).fetchone()[0]

    yearly = db.execute(f"""
        SELECT IFNULL(SUM(amount),0)
        FROM transactions
        WHERE strftime('%Y', date) = strftime('%Y','now')
        {user_filter}
    """, params).fetchone()[0]

    db.close()

    return render_template(
        "dashboard.html",
        transactions=transactions,
        role=session["role"],
        username=session["username"],
        daily=daily,
        weekly=weekly,
        monthly=monthly,
        yearly=yearly
    )

# ---------- ADD TRANSACTION (USER ONLY) ----------
@app.route("/add", methods=["POST"])
def add():
    if session.get("role") != "user":
        flash("Admins cannot add transactions")
        return redirect("/dashboard")

    amount = float(request.form["amount"])
    date = request.form["date"]
    category = request.form["category"]
    note = request.form.get("note") or "—"

    if amount <= 0:
        flash("Amount must be positive")
        return redirect("/dashboard")

    if date > datetime.now().strftime("%Y-%m-%d"):
        flash("Future date not allowed")
        return redirect("/dashboard")

    db = get_db()
    db.execute(
        "INSERT INTO transactions (amount, date, category, note, user_id) VALUES (?, ?, ?, ?, ?)",
        (amount, date, category, note, session["user_id"])
    )
    db.commit()
    db.close()

    flash("Transaction added")
    return redirect("/dashboard")

# ---------- DELETE TRANSACTION (ADMIN ONLY) ----------
@app.route("/delete_transaction/<int:id>")
def delete_transaction(id):
    if session.get("role") != "admin":
        flash("Unauthorized")
        return redirect("/dashboard")

    db = get_db()
    db.execute("DELETE FROM transactions WHERE id=?", (id,))
    db.commit()
    db.close()

    flash("Transaction deleted")
    return redirect("/dashboard")

# ---------- EXPORT CSV ----------
@app.route("/export/csv")
def export_csv():
    if "user_id" not in session:
        return redirect("/")

    db = get_db()
    if session["role"] == "admin":
        rows = db.execute("""
            SELECT date, category, amount, note, username
            FROM transactions t JOIN users u ON t.user_id=u.id
        """).fetchall()
        headers = ["Date", "Category", "Amount", "Note", "User"]
    else:
        rows = db.execute("""
            SELECT date, category, amount, note FROM transactions WHERE user_id=?
        """, (session["user_id"],)).fetchall()
        headers = ["Date", "Category", "Amount", "Note"]
    db.close()

    with open("expenses.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        for r in rows:
            writer.writerow(r)

    return send_file("expenses.csv", as_attachment=True)

# ---------- EXPORT PDF ----------
@app.route("/export/pdf")
def export_pdf():
    if "user_id" not in session:
        return redirect("/")

    db = get_db()
    if session["role"] == "admin":
        rows = db.execute("""
            SELECT date, category, amount, note, username
            FROM transactions t JOIN users u ON t.user_id=u.id
        """).fetchall()
    else:
        rows = db.execute("""
            SELECT date, category, amount, note FROM transactions WHERE user_id=?
        """, (session["user_id"],)).fetchall()
    db.close()

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", size=10)
    pdf.cell(0, 10, "Expense Report", ln=True)

    for r in rows:
        pdf.cell(0, 8, " | ".join(map(str, r)), ln=True)

    pdf.output("expenses.pdf")
    return send_file("expenses.pdf", as_attachment=True)

# ---------- ADMIN PANEL ----------
@app.route("/admin")
def admin():
    if session.get("role") != "admin":
        return redirect("/dashboard")
    db = get_db()
    users = db.execute("SELECT * FROM users").fetchall()
    db.close()
    return render_template("admin.html", users=users)

# ---------- REGISTER USER ----------
@app.route("/register", methods=["GET", "POST"])
def register():
    if session.get("role") != "admin":
        return redirect("/dashboard")

    if request.method == "POST":
        try:
            db = get_db()
            db.execute(
                "INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
                (
                    request.form["username"],
                    generate_password_hash(request.form["password"]),
                    request.form["role"]
                )
            )
            db.commit()
            db.close()
            flash("User created")
            return redirect("/admin")
        except:
            flash("Username exists")
    return render_template("register.html")

# ---------- DELETE USER ----------
@app.route("/delete_user/<int:id>")
def delete_user(id):
    if session.get("role") != "admin" or id == session["user_id"]:
        return redirect("/admin")

    db = get_db()
    db.execute("DELETE FROM transactions WHERE user_id=?", (id,))
    db.execute("DELETE FROM users WHERE id=?", (id,))
    db.commit()
    db.close()
    flash("User deleted")
    return redirect("/admin")

if __name__ == "__main__":
    if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)


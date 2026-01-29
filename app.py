from flask import Flask, render_template, request, redirect, session, flash, send_file
import psycopg2
import psycopg2.extras
import csv, os
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
from fpdf import FPDF

app = Flask(__name__)
app.secret_key = "expense-tracker-secret"

# ---------- DATABASE ----------
def get_db():
    return psycopg2.connect(
        os.environ["DATABASE_URL"],
        cursor_factory=psycopg2.extras.RealDictCursor
    )

# ---------- LOGIN ----------
@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        db = get_db()
        cur = db.cursor()
        cur.execute(
            "SELECT * FROM users WHERE username=%s",
            (request.form["username"],)
        )
        user = cur.fetchone()
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
    cur = db.cursor()

    if session["role"] == "admin":
        cur.execute("""
            SELECT t.*, u.username
            FROM transactions t
            JOIN users u ON t.user_id = u.id
            ORDER BY date DESC
        """)
        transactions = cur.fetchall()
    else:
        cur.execute("""
            SELECT *
            FROM transactions
            WHERE user_id=%s
            ORDER BY date DESC
        """, (session["user_id"],))
        transactions = cur.fetchall()

    def stat(query, params=()):
        cur.execute(query, params)
        return cur.fetchone()["sum"] or 0

    uid = session["user_id"]

    daily = stat(
        "SELECT SUM(amount) FROM transactions WHERE date=CURRENT_DATE AND (%s OR user_id=%s)",
        (session["role"] == "admin", uid)
    )

    weekly = stat(
        "SELECT SUM(amount) FROM transactions WHERE date >= CURRENT_DATE - INTERVAL '6 days' AND (%s OR user_id=%s)",
        (session["role"] == "admin", uid)
    )

    monthly = stat(
        "SELECT SUM(amount) FROM transactions WHERE date >= date_trunc('month', CURRENT_DATE) AND (%s OR user_id=%s)",
        (session["role"] == "admin", uid)
    )

    yearly = stat(
        "SELECT SUM(amount) FROM transactions WHERE date >= date_trunc('year', CURRENT_DATE) AND (%s OR user_id=%s)",
        (session["role"] == "admin", uid)
    )

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

# ---------- ADD TRANSACTION ----------
@app.route("/add", methods=["POST"])
def add():
    if session.get("role") != "user":
        flash("Admins cannot add transactions")
        return redirect("/dashboard")

    amount = float(request.form["amount"])
    date = request.form["date"]
    category = request.form["category"]
    note = request.form.get("note") or "—"

    if amount <= 0 or date > datetime.now().strftime("%Y-%m-%d"):
        flash("Invalid input")
        return redirect("/dashboard")

    db = get_db()
    cur = db.cursor()
    cur.execute("""
        INSERT INTO transactions (amount, date, category, note, user_id)
        VALUES (%s, %s, %s, %s, %s)
    """, (amount, date, category, note, session["user_id"]))
    db.commit()
    db.close()

    flash("Transaction added")
    return redirect("/dashboard")

# ---------- DELETE TRANSACTION ----------
@app.route("/delete_transaction/<int:id>")
def delete_transaction(id):
    if session.get("role") != "admin":
        return redirect("/dashboard")

    db = get_db()
    cur = db.cursor()
    cur.execute("DELETE FROM transactions WHERE id=%s", (id,))
    db.commit()
    db.close()

    flash("Transaction deleted")
    return redirect("/dashboard")

# ---------- ADMIN ----------
@app.route("/admin")
def admin():
    if session.get("role") != "admin":
        return redirect("/dashboard")

    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT * FROM users")
    users = cur.fetchall()
    db.close()

    return render_template("admin.html", users=users)

# ---------- REGISTER ----------
@app.route("/register", methods=["GET", "POST"])
def register():
    if session.get("role") != "admin":
        return redirect("/dashboard")

    if request.method == "POST":
        try:
            db = get_db()
            cur = db.cursor()
            cur.execute("""
                INSERT INTO users (username, password, role)
                VALUES (%s, %s, %s)
            """, (
                request.form["username"],
                generate_password_hash(request.form["password"]),
                request.form["role"]
            ))
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
    cur = db.cursor()
    cur.execute("DELETE FROM transactions WHERE user_id=%s", (id,))
    cur.execute("DELETE FROM users WHERE id=%s", (id,))
    db.commit()
    db.close()

    flash("User deleted")
    return redirect("/admin")

@app.errorhandler(Exception)
def handle_exception(e):
    return f"ERROR: {str(e)}", 500


# ---------- RUN ----------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

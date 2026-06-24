import datetime
import sqlite3
from flask import Flask, render_template, request, redirect, session, g, flash, url_for
from werkzeug.security import generate_password_hash, check_password_hash
from flask_wtf import CSRFProtect

app = Flask(__name__)
app.secret_key = "supersecretkey"


DATABASE = "train_reservation.db"

# Database Connection
def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
    return db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]
        
        print("Email:", email)  # Debug print
        print("Password:", password)  # Debug print

        db = get_db()
        user = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        
        print("User:", user)  # Debug print

        if user and check_password_hash(user["password"], password):
            session["user_id"] = user["user_id"]
            session["username"] = user["username"]
            session["role"] = user["role"]
            flash("Login successful!", "success")

            if user["role"] == "user":
                return redirect(url_for("user_dashboard"))
            elif user["role"] == "admin":
                return redirect(url_for("admin_dashboard"))
            elif user["role"] == "counter":
                return redirect(url_for("counter_dashboard"))
            elif user["role"] == "scheduler":
                return redirect(url_for("scheduler_dashboard"))
        else:
            flash("Invalid email or password!", "danger")

    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out successfully!", "info")
    return redirect(url_for("login"))

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form["username"]
        email = request.form["email"]
        password = request.form["password"]
        hashed_password = generate_password_hash(password)

        db = get_db()
        try:
            db.execute("INSERT INTO users (username, email, password, role) VALUES (?, ?, ?, 'user')",
                       (username, email, hashed_password))
            db.commit()
            flash("Registration successful! Please login.", "success")
            return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            flash("Email already registered!", "danger")

    return render_template("register.html")

# Dashboard (After Login)
@app.route("/user_dashboard", methods=["GET"])
def user_dashboard():
    if "user_id" not in session or session["role"] != "user":
        flash("Access denied!", "danger")
        return redirect(url_for("login"))

    db = get_db()

    # Fetch train count for Home section
    train_count = db.execute("SELECT COUNT(*) FROM trains").fetchone()[0]

    # Fetch all stations for dropdowns
    stations = db.execute("SELECT station_id, station_name FROM stations").fetchall()

    # Fetch user tickets for My Tickets section
    user_id = session["user_id"]
    tickets = db.execute("""
        SELECT b.booking_id, t.train_name, dep.station_name AS departure_station, arr.station_name AS arrival_station,
               s.departure_time, s.arrival_time, b.class, b.seat_number
        FROM bookings b
        JOIN schedules s ON b.schedule_id = s.schedule_id
        JOIN trains t ON s.train_id = t.train_id
        JOIN stations dep ON s.departure_station_id = dep.station_id
        JOIN stations arr ON s.arrival_station_id = arr.station_id
        WHERE b.user_id = ?
    """, (user_id,)).fetchall()

    # Fetch schedules based on search filters
    departure_station = request.args.get("departure_station")
    arrival_station = request.args.get("arrival_station")
    date = request.args.get("date")

    # Pagination logic
    page = request.args.get("page", 1, type=int)
    per_page = 5
    offset = (page - 1) * per_page

    # Build the query based on filters
    query = """
        SELECT s.schedule_id, t.train_number, t.train_name, dep.station_name AS departure_station,
               arr.station_name AS arrival_station, s.departure_time, s.arrival_time
        FROM schedules s
        JOIN trains t ON s.train_id = t.train_id
        JOIN stations dep ON s.departure_station_id = dep.station_id
        JOIN stations arr ON s.arrival_station_id = arr.station_id
        WHERE 1=1
    """
    params = []

    if departure_station:
        query += " AND s.departure_station_id = ?"
        params.append(departure_station)
    if arrival_station:
        query += " AND s.arrival_station_id = ?"
        params.append(arrival_station)
    if date:
        query += " AND date(s.departure_time) = ?"
        params.append(date)

    query += " LIMIT ? OFFSET ?"
    params.extend([per_page, offset])

    schedules = db.execute(query, params).fetchall()

    # Pagination controls
    total_schedules = db.execute("""
        SELECT COUNT(*)
        FROM schedules s
        WHERE 1=1
        """ + (" AND s.departure_station_id = ?" if departure_station else "") +
        (" AND s.arrival_station_id = ?" if arrival_station else "") +
        (" AND date(s.departure_time) = ?" if date else ""),
        params[:-2]  # Exclude LIMIT and OFFSET params
    ).fetchone()[0]

    total_pages = (total_schedules + per_page - 1) // per_page
    previous_page = page - 1 if page > 1 else None
    next_page = page + 1 if page < total_pages else None

    return render_template("user_dashboard.html", train_count=train_count, stations=stations, schedules=schedules, tickets=tickets,
                           current_page=page, previous_page=previous_page, next_page=next_page)

@app.route("/admin_dashboard", methods=["GET"])
def admin_dashboard():
    if "user_id" not in session or session["role"] != "admin":
        flash("Access denied!", "danger")
        return redirect(url_for("login"))

    db = get_db()

    # Pagination parameters
    page = request.args.get("page", 1, type=int)  # Default to page 1
    per_page = 5  # Number of records per page
    offset = (page - 1) * per_page

    # Search users by username
    search_username = request.args.get("search_username")
    if search_username:
        users = db.execute("SELECT * FROM users WHERE username LIKE ? LIMIT ? OFFSET ?",
                           ('%' + search_username + '%', per_page, offset)).fetchall()
        total_users = db.execute("SELECT COUNT(*) FROM users WHERE username LIKE ?", ('%' + search_username + '%',)).fetchone()[0]
    else:
        users = db.execute("SELECT * FROM users LIMIT ? OFFSET ?", (per_page, offset)).fetchall()
        total_users = db.execute("SELECT COUNT(*) FROM users").fetchone()[0]

    # Search trains by train name
    search_train = request.args.get("search_train")
    if search_train:
        trains = db.execute("SELECT * FROM trains WHERE train_name LIKE ? LIMIT ? OFFSET ?",
                            ('%' + search_train + '%', per_page, offset)).fetchall()
        total_trains = db.execute("SELECT COUNT(*) FROM trains WHERE train_name LIKE ?", ('%' + search_train + '%',)).fetchone()[0]
    else:
        trains = db.execute("SELECT * FROM trains LIMIT ? OFFSET ?", (per_page, offset)).fetchall()
        total_trains = db.execute("SELECT COUNT(*) FROM trains").fetchone()[0]

    # Calculate the total number of pages
    total_pages_users = (total_users // per_page) + (1 if total_users % per_page else 0)
    total_pages_trains = (total_trains // per_page) + (1 if total_trains % per_page else 0)

    return render_template("admin_dashboard.html", users=users, trains=trains, 
                           total_pages_users=total_pages_users, total_pages_trains=total_pages_trains,
                           current_page_users=page, current_page_trains=page)

@app.route("/delete_train/<int:train_id>", methods=["POST"])
def delete_train(train_id):
    if "user_id" not in session or session["role"] != "admin":
        flash("Access denied!", "danger")
        return redirect(url_for("login"))

    db = get_db()
    db.execute("DELETE FROM trains WHERE train_id = ?", (train_id,))
    db.commit()
    flash("Train deleted successfully!", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/delete_user/<int:user_id>", methods=["POST"])
def delete_user(user_id):
    if "user_id" not in session or session["role"] != "admin":
        flash("Access denied!", "danger")
        return redirect(url_for("login"))

    db = get_db()
    db.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
    db.commit()
    flash("User deleted successfully!", "success")
    return redirect(url_for("admin_dashboard"))

@app.route("/add_officer", methods=["POST"])
def add_officer():
    if "user_id" not in session or session["role"] != "admin":
        flash("Access denied!", "danger")
        return redirect(url_for("login"))

    username = request.form["username"]
    email = request.form["email"]
    password = request.form["password"]
    confirm_password = request.form["confirm_password"]
    role = request.form["role"]

    if password != confirm_password:
        flash("Passwords do not match!", "danger")
        return redirect(url_for("admin_dashboard"))

    hashed_password = generate_password_hash(password)

    db = get_db()
    try:
        db.execute("INSERT INTO users (username, email, password, role) VALUES (?, ?, ?, ?)",
                   (username, email, hashed_password, role))
        db.commit()
        flash("Officer added successfully!", "success")
    except sqlite3.IntegrityError:
        flash("Email already registered!", "danger")

    return redirect(url_for("admin_dashboard"))

@app.route("/counter_dashboard", methods=["GET"])
def counter_dashboard():
    if "user_id" not in session or session["role"] != "counter":
        flash("Access denied!", "danger")
        return redirect(url_for("login"))

    db = get_db()

    # Search bookings by booking ID
    search_booking_id = request.args.get("search_booking_id")
    bookings = []
    if search_booking_id:
        bookings = db.execute("""
            SELECT b.booking_id, t.train_name, dep.station_name AS departure_station, arr.station_name AS arrival_station,
                   s.departure_time, s.arrival_time, b.class, b.seat_number
            FROM bookings b
            JOIN schedules s ON b.schedule_id = s.schedule_id
            JOIN trains t ON s.train_id = t.train_id
            JOIN stations dep ON s.departure_station_id = dep.station_id
            JOIN stations arr ON s.arrival_station_id = arr.station_id
            WHERE b.booking_id = ?
        """, (search_booking_id,)).fetchall()

    return render_template("counter_dashboard.html", bookings=bookings)

@app.route("/cancel_booking/<int:booking_id>", methods=["GET"])
def cancel_booking(booking_id):
    if "user_id" not in session or session["role"] != "counter":
        flash("Access denied!", "danger")
        return redirect(url_for("login"))

    db = get_db()
    db.execute("DELETE FROM bookings WHERE booking_id = ?", (booking_id,))
    db.commit()
    flash("Booking cancelled successfully!", "success")
    return redirect(url_for("counter_dashboard"))

# Add the station pagination logic to the scheduler_dashboard route
@app.route("/scheduler_dashboard", methods=["GET"])
def scheduler_dashboard():
    if "user_id" not in session or session["role"] != "scheduler":
        flash("Access denied!", "danger")
        return redirect(url_for("login"))

    db = get_db()

    # Pagination logic for trains
    page = request.args.get("page", 1, type=int)
    per_page = 5
    offset = (page - 1) * per_page

    trains = db.execute("SELECT * FROM trains LIMIT ? OFFSET ?", (per_page, offset)).fetchall()
    total_trains = db.execute("SELECT COUNT(*) FROM trains").fetchone()[0]

    total_pages = (total_trains + per_page - 1) // per_page
    previous_page = page - 1 if page > 1 else None
    next_page = page + 1 if page < total_pages else None

    # Pagination logic for stations
    stations = db.execute("SELECT * FROM stations LIMIT ? OFFSET ?", (per_page, offset)).fetchall()
    total_stations = db.execute("SELECT COUNT(*) FROM stations").fetchone()[0]

    # Fetch all trains and stations for dropdowns
    all_trains = db.execute("SELECT * FROM trains").fetchall()
    all_stations = db.execute("SELECT * FROM stations").fetchall()

    # Debug prints
    print("Trains:", trains)
    print("Stations:", stations)
    print("All Trains:", all_trains)
    print("All Stations:", all_stations)

    return render_template("scheduler_dashboard.html", trains=trains, stations=stations, all_trains=all_trains, 
                           all_stations=all_stations, current_page=page, previous_page=previous_page, next_page=next_page)

@app.route("/add_train", methods=["POST"])
def add_train():
    if "user_id" not in session or session["role"] != "scheduler":
        flash("Access denied!", "danger")
        return redirect(url_for("login"))

    train_number = request.form["train_number"]
    train_name = request.form["train_name"]
    capacity = request.form["capacity"]
    classes = request.form.getlist("classes")

    if int(capacity) < 0:
        flash("Capacity cannot be negative!", "danger")
        return redirect(url_for("scheduler_dashboard"))

    classes_str = ",".join(classes)

    db = get_db()
    db.execute("INSERT INTO trains (train_number, train_name, capacity, classes) VALUES (?, ?, ?, ?)",
               (train_number, train_name, capacity, classes_str))
    db.commit()
    flash("Train added successfully!", "success")
    return redirect(url_for("scheduler_dashboard"))

@app.route("/add_station", methods=["POST"])
def add_station():
    if "user_id" not in session or session["role"] != "scheduler":
        flash("Access denied!", "danger")
        return redirect(url_for("login"))

    station_code = request.form["station_code"]
    station_name = request.form["station_name"]

    db = get_db()
    db.execute("INSERT INTO stations (station_code, station_name) VALUES (?, ?)",
               (station_code, station_name))
    db.commit()
    flash("Station added successfully!", "success")
    return redirect(url_for("scheduler_dashboard"))

@app.route("/schedule_train", methods=["POST"])
def schedule_train():
    if "user_id" not in session or session["role"] != "scheduler":
        flash("Access denied!", "danger")
        return redirect(url_for("login"))

    train_id = request.form["train_id"]
    departure_station_id = request.form["departure_station_id"]
    arrival_station_id = request.form["arrival_station_id"]
    departure_time = request.form["departure_time"]
    arrival_time = request.form["arrival_time"]

    db = get_db()
    db.execute("""
        INSERT INTO schedules (train_id, departure_station_id, arrival_station_id, departure_time, arrival_time)
        VALUES (?, ?, ?, ?, ?)
    """, (train_id, departure_station_id, arrival_station_id, departure_time, arrival_time))
    db.commit()
    flash("Train scheduled successfully!", "success")
    return redirect(url_for("scheduler_dashboard"))

@app.route("/manage_schedules", methods=["GET"])
def manage_schedules():
    if "user_id" not in session or session["role"] != "scheduler":
        flash("Access denied!", "danger")
        return redirect(url_for("login"))

    db = get_db()

    search_schedule = request.args.get("search_schedule")
    page = request.args.get("page", 1, type=int)
    per_page = 5
    offset = (page - 1) * per_page

    if search_schedule:
        schedules = db.execute("""
            SELECT s.schedule_id, t.train_name, dep.station_name AS departure_station, arr.station_name AS arrival_station,
                   s.departure_time, s.arrival_time
            FROM schedules s
            JOIN trains t ON s.train_id = t.train_id
            JOIN stations dep ON s.departure_station_id = dep.station_id
            JOIN stations arr ON s.arrival_station_id = arr.station_id
            WHERE t.train_name LIKE ? OR dep.station_name LIKE ? OR arr.station_name LIKE ?
            LIMIT ? OFFSET ?
        """, ('%' + search_schedule + '%', '%' + search_schedule + '%', '%' + search_schedule + '%', per_page, offset)).fetchall()
        total_schedules = db.execute("""
            SELECT COUNT(*)
            FROM schedules s
            JOIN trains t ON s.train_id = t.train_id
            JOIN stations dep ON s.departure_station_id = dep.station_id
            JOIN stations arr ON s.arrival_station_id = arr.station_id
            WHERE t.train_name LIKE ? OR dep.station_name LIKE ? OR arr.station_name LIKE ?
        """, ('%' + search_schedule + '%', '%' + search_schedule + '%', '%' + search_schedule + '%')).fetchone()[0]
    else:
        schedules = db.execute("""
            SELECT s.schedule_id, t.train_name, dep.station_name AS departure_station, arr.station_name AS arrival_station,
                   s.departure_time, s.arrival_time
            FROM schedules s
            JOIN trains t ON s.train_id = t.train_id
            JOIN stations dep ON s.departure_station_id = dep.station_id
            JOIN stations arr ON s.arrival_station_id = arr.station_id
            LIMIT ? OFFSET ?
        """, (per_page, offset)).fetchall()
        total_schedules = db.execute("SELECT COUNT(*) FROM schedules").fetchone()[0]

    total_pages = (total_schedules + per_page - 1) // per_page
    previous_page = page - 1 if page > 1 else None
    next_page = page + 1 if page < total_pages else None

    return render_template("scheduler_dashboard.html", schedules=schedules, current_page=page,
                           previous_page=previous_page, next_page=next_page)

@app.route("/delete_schedule/<int:schedule_id>", methods=["POST"])
def delete_schedule(schedule_id):
    if "user_id" not in session or session["role"] != "scheduler":
        flash("Access denied!", "danger")
        return redirect(url_for("login"))

    db = get_db()

    # Delete the schedule from the database
    db.execute("DELETE FROM schedules WHERE schedule_id = ?", (schedule_id,))
    db.commit()

    flash("Schedule deleted successfully!", "success")
    return redirect(url_for("scheduler_dashboard"))

@app.route("/book_ticket", methods=["POST"])
def book_ticket():
    if "user_id" not in session or session["role"] != "user":
        flash("Access denied!", "danger")
        return redirect(url_for("login"))

    schedule_id = request.form["schedule_id"]
    class_name = request.form["class"]
    seat_number = request.form["seat_number"]
    user_id = session["user_id"]
    current_time = datetime.datetime.now()
    booking_date = current_time.strftime("%Y-%m-%d")
    booking_time = current_time.strftime("%H:%M:%S")

    db = get_db()
    db.execute("""
        INSERT INTO bookings (schedule_id, user_id, class, seat_number, booking_date, booking_time)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (schedule_id, user_id, class_name, seat_number, booking_date, booking_time))
    db.commit()
    flash("Booking confirmed!", "success")
    return redirect(url_for("user_dashboard"))

if __name__ == "__main__":
    app.run(debug=True)

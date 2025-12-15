from flask import Flask, render_template, request, redirect, url_for, session, flash
import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

app = Flask(__name__)
app.secret_key = "any_random_string"

# --- ADMIN CREDENTIALS (basic capstone) ---
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin123"


# ----------------- DB HELPERS -----------------
def get_db():
    conn = sqlite3.connect("event_booking.db")
    conn.row_factory = sqlite3.Row
    return conn


def is_admin():
    return session.get("is_admin") is True


def login_required():
    return "user_id" in session


def get_products():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM products ORDER BY id DESC")
    products = cur.fetchall()
    conn.close()
    return products


def get_cart_count():
    if not login_required():
        return 0
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT COALESCE(SUM(qty),0) AS c FROM cart_items WHERE user_id = ?", (session["user_id"],))
    count = cur.fetchone()["c"]
    conn.close()
    return count or 0


# ----------------- CUSTOMER PAGES -----------------
@app.route("/")
def home():
    products = get_products()
    cart_count = get_cart_count()
    return render_template("index.html", products=products, cart_count=cart_count)


# ----------------- AUTH -----------------
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form["name"].strip()
        email = request.form["email"].strip().lower()
        password = request.form["password"]

        conn = get_db()
        cur = conn.cursor()
        try:
            cur.execute(
                "INSERT INTO users (name, email, password) VALUES (?, ?, ?)",
                (name, email, generate_password_hash(password))
            )
            conn.commit()
        except sqlite3.IntegrityError:
            flash("Email already registered. Please login.")
            conn.close()
            return redirect(url_for("login"))

        conn.close()
        flash("Registration successful. Please login.")
        return redirect(url_for("login"))

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"].strip().lower()
        password = request.form["password"]

        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE email = ?", (email,))
        user = cur.fetchone()
        conn.close()

        if user and check_password_hash(user["password"], password):
            session["user_id"] = user["id"]
            session["user_name"] = user["name"]
            flash("Logged in successfully.")
            return redirect(url_for("home"))

        flash("Invalid email or password.")
        return redirect(url_for("login"))

    return render_template("login.html")


@app.route("/logout")
def logout():
    # don't clear admin unless you want to
    is_admin_flag = session.get("is_admin")
    session.clear()
    if is_admin_flag:
        session["is_admin"] = True
    flash("Logged out.")
    return redirect(url_for("home"))


# ----------------- CART -----------------
@app.route("/add_to_cart/<int:product_id>", methods=["POST"])
def add_to_cart(product_id):
    if not login_required():
        flash("Please login to add items to cart.")
        return redirect(url_for("login"))

    conn = get_db()
    cur = conn.cursor()

    # Check stock
    cur.execute("SELECT stock FROM products WHERE id = ?", (product_id,))
    p = cur.fetchone()
    if not p:
        conn.close()
        flash("Product not found.")
        return redirect(url_for("home"))
    if p["stock"] <= 0:
        conn.close()
        flash("Out of stock.")
        return redirect(url_for("home"))

    # Insert or increase qty
    user_id = session["user_id"]
    cur.execute("SELECT id, qty FROM cart_items WHERE user_id=? AND product_id=?", (user_id, product_id))
    item = cur.fetchone()

    if item:
        cur.execute("UPDATE cart_items SET qty = qty + 1 WHERE id = ?", (item["id"],))
    else:
        cur.execute("INSERT INTO cart_items (user_id, product_id, qty) VALUES (?, ?, 1)", (user_id, product_id))

    conn.commit()
    conn.close()
    flash("Added to cart.")
    return redirect(url_for("home"))


@app.route("/cart")
def cart():
    if not login_required():
        flash("Please login to view cart.")
        return redirect(url_for("login"))

    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT ci.id AS cart_id, ci.qty, p.id AS product_id, p.name, p.price, p.stock
        FROM cart_items ci
        JOIN products p ON ci.product_id = p.id
        WHERE ci.user_id = ?
        ORDER BY ci.id DESC
    """, (session["user_id"],))
    items = cur.fetchall()

    total = 0.0
    for it in items:
        total += float(it["price"]) * int(it["qty"])

    conn.close()
    return render_template("cart.html", items=items, total=total, cart_count=get_cart_count())


@app.route("/cart/update/<int:cart_id>", methods=["POST"])
def cart_update(cart_id):
    if not login_required():
        flash("Please login first.")
        return redirect(url_for("login"))

    qty = int(request.form.get("qty", 1))
    if qty < 1:
        qty = 1

    conn = get_db()
    cur = conn.cursor()
    # Ensure user owns item
    cur.execute("SELECT user_id FROM cart_items WHERE id = ?", (cart_id,))
    row = cur.fetchone()
    if not row or row["user_id"] != session["user_id"]:
        conn.close()
        flash("Invalid cart item.")
        return redirect(url_for("cart"))

    cur.execute("UPDATE cart_items SET qty = ? WHERE id = ?", (qty, cart_id))
    conn.commit()
    conn.close()
    flash("Cart updated.")
    return redirect(url_for("cart"))


@app.route("/cart/remove/<int:cart_id>", methods=["POST"])
def cart_remove(cart_id):
    if not login_required():
        flash("Please login first.")
        return redirect(url_for("login"))

    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM cart_items WHERE id = ? AND user_id = ?", (cart_id, session["user_id"]))
    conn.commit()
    conn.close()
    flash("Removed from cart.")
    return redirect(url_for("cart"))


# ----------------- CHECKOUT / ORDERS -----------------
@app.route("/checkout", methods=["POST"])
def checkout():
    if not login_required():
        flash("Please login first.")
        return redirect(url_for("login"))

    user_id = session["user_id"]
    conn = get_db()
    cur = conn.cursor()

    # Load cart
    cur.execute("""
        SELECT ci.product_id, ci.qty, p.price, p.stock
        FROM cart_items ci
        JOIN products p ON ci.product_id = p.id
        WHERE ci.user_id = ?
    """, (user_id,))
    cart_rows = cur.fetchall()

    if not cart_rows:
        conn.close()
        flash("Your cart is empty.")
        return redirect(url_for("cart"))

    # Check stock
    for r in cart_rows:
        if r["qty"] > r["stock"]:
            conn.close()
            flash("Not enough stock for one or more items.")
            return redirect(url_for("cart"))

    # Create order
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cur.execute("INSERT INTO orders (user_id, created_at, status) VALUES (?, ?, 'Placed')", (user_id, created_at))
    order_id = cur.lastrowid

    # Create order items + reduce stock
    for r in cart_rows:
        cur.execute(
            "INSERT INTO order_items (order_id, product_id, qty, price_each) VALUES (?, ?, ?, ?)",
            (order_id, r["product_id"], r["qty"], r["price"])
        )
        cur.execute("UPDATE products SET stock = stock - ? WHERE id = ?", (r["qty"], r["product_id"]))

    # Clear cart
    cur.execute("DELETE FROM cart_items WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

    flash("Order placed successfully!")
    return redirect(url_for("orders"))


@app.route("/orders")
def orders():
    if not login_required():
        flash("Please login to view orders.")
        return redirect(url_for("login"))

    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT * FROM orders
        WHERE user_id = ?
        ORDER BY id DESC
    """, (session["user_id"],))
    orders_list = cur.fetchall()

    # Load items for each order (basic approach)
    orders_with_items = []
    for o in orders_list:
        cur.execute("""
            SELECT oi.qty, oi.price_each, p.name
            FROM order_items oi
            JOIN products p ON oi.product_id = p.id
            WHERE oi.order_id = ?
        """, (o["id"],))
        items = cur.fetchall()
        orders_with_items.append((o, items))

    conn.close()
    return render_template("orders.html", orders=orders_with_items, cart_count=get_cart_count())


# ----------------- ADMIN -----------------
@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"].strip()

        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session["is_admin"] = True
            flash("Admin logged in.")
            return redirect(url_for("admin_products"))
        flash("Invalid admin credentials.")
        return redirect(url_for("admin_login"))

    return render_template("admin_login.html")


@app.route("/admin/logout")
def admin_logout():
    session.pop("is_admin", None)
    flash("Admin logged out.")
    return redirect(url_for("home"))


@app.route("/admin/products")
def admin_products():
    if not is_admin():
        flash("Admin access only.")
        return redirect(url_for("admin_login"))

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM products ORDER BY id DESC")
    products = cur.fetchall()
    conn.close()
    return render_template("admin_products.html", products=products)


@app.route("/admin/products/add", methods=["GET", "POST"])
def admin_add_product():
    if not is_admin():
        flash("Admin access only.")
        return redirect(url_for("admin_login"))

    if request.method == "POST":
        name = request.form["name"].strip()
        description = request.form["description"].strip()
        price = float(request.form["price"])
        stock = int(request.form["stock"])

        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO products (name, description, price, stock) VALUES (?, ?, ?, ?)",
            (name, description, price, stock)
        )
        conn.commit()
        conn.close()
        flash("Product added.")
        return redirect(url_for("admin_products"))

    return render_template("admin_product_form.html", mode="Add", product=None)


@app.route("/admin/products/edit/<int:product_id>", methods=["GET", "POST"])
def admin_edit_product(product_id):
    if not is_admin():
        flash("Admin access only.")
        return redirect(url_for("admin_login"))

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM products WHERE id = ?", (product_id,))
    product = cur.fetchone()

    if not product:
        conn.close()
        flash("Product not found.")
        return redirect(url_for("admin_products"))

    if request.method == "POST":
        name = request.form["name"].strip()
        description = request.form["description"].strip()
        price = float(request.form["price"])
        stock = int(request.form["stock"])

        cur.execute(
            "UPDATE products SET name=?, description=?, price=?, stock=? WHERE id=?",
            (name, description, price, stock, product_id)
        )
        conn.commit()
        conn.close()
        flash("Product updated.")
        return redirect(url_for("admin_products"))

    conn.close()
    return render_template("admin_product_form.html", mode="Edit", product=product)


@app.route("/admin/products/delete/<int:product_id>", methods=["POST"])
def admin_delete_product(product_id):
    if not is_admin():
        flash("Admin access only.")
        return redirect(url_for("admin_login"))

    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM products WHERE id = ?", (product_id,))
    conn.commit()
    conn.close()
    flash("Product deleted.")
    return redirect(url_for("admin_products"))

@app.route("/admin/orders")
def admin_orders():
    if not is_admin():
        flash("Admin access only.")
        return redirect(url_for("admin_login"))

    conn = get_db()
    cur = conn.cursor()

    # get all orders with user info
    cur.execute("""
        SELECT o.id, o.created_at, o.status, u.name, u.email
        FROM orders o
        JOIN users u ON o.user_id = u.id
        ORDER BY o.id DESC
    """)
    orders = cur.fetchall()

    orders_with_items = []

    for o in orders:
        cur.execute("""
            SELECT oi.qty, oi.price_each, p.name
            FROM order_items oi
            JOIN products p ON oi.product_id = p.id
            WHERE oi.order_id = ?
        """, (o["id"],))
        items = cur.fetchall()
        orders_with_items.append((o, items))

    conn.close()
    return render_template("admin_orders.html", orders=orders_with_items)

@app.route("/admin/orders/update/<int:order_id>", methods=["POST"])
def admin_update_order_status(order_id):
    if not is_admin():
        flash("Admin access only.")
        return redirect(url_for("admin_login"))

    new_status = request.form.get("status", "Placed")

    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE orders SET status = ? WHERE id = ?", (new_status, order_id))
    conn.commit()
    conn.close()

    flash(f"Order #{order_id} status updated to {new_status}.")
    return redirect(url_for("admin_orders"))


if __name__ == "__main__":
    app.run(debug=True)

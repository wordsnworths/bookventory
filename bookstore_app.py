import streamlit as st
import sqlite3
import pandas as pd
import requests
import datetime
from functools import lru_cache
from io import BytesIO
import plotly.express as px

# --------------------------------------------------
# APP CONFIG
# --------------------------------------------------
st.set_page_config(
    page_title="Bookventory",
    page_icon="📚",
    layout="wide"
)

# --------------------------------------------------
# DATABASE (ROBUST SQLITE)
# --------------------------------------------------
DB_NAME = "bookstore.db"

def get_conn():
    return sqlite3.connect(DB_NAME, check_same_thread=False)

def init_db():
    conn = get_conn()
    c = conn.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS books (
        isbn TEXT PRIMARY KEY,
        title TEXT,
        author TEXT,
        publisher TEXT,
        genre TEXT,
        summary TEXT,
        mrp REAL,
        stock INTEGER DEFAULT 0,
        shelf_location TEXT,
        cover_url TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS sales (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        isbn TEXT,
        qty INTEGER,
        sale_date DATE
    )
    """)

    c.execute("CREATE INDEX IF NOT EXISTS idx_sales_date ON sales(sale_date)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_sales_isbn ON sales(isbn)")

    conn.commit()
    conn.close()

init_db()

# --------------------------------------------------
# SAFE DB HELPERS
# --------------------------------------------------
def db_query(sql, params=()):
    with get_conn() as conn:
        return pd.read_sql(sql, conn, params=params)

def db_execute(sql, params=()):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(sql, params)
        conn.commit()

# --------------------------------------------------
# GOOGLE BOOKS API (FIXED & CLOUD SAFE)
# --------------------------------------------------
@lru_cache(maxsize=3000)
def fetch_book_metadata(isbn):
    if not isbn or len(isbn) < 10:
        return None

    url = "https://www.googleapis.com/books/v1/volumes"
    params = {"q": f"isbn:{isbn}"}
    headers = {
        "User-Agent": "Bookventory/1.0",
        "Accept": "application/json"
    }

    try:
        r = requests.get(url, params=params, headers=headers, timeout=6)
        if r.status_code != 200:
            return None

        data = r.json()
        if "items" not in data:
            return None

        info = data["items"][0].get("volumeInfo", {})
        return {
            "title": info.get("title", "Unknown"),
            "author": ", ".join(info.get("authors", ["Unknown"])),
            "publisher": info.get("publisher", "Unknown"),
            "genre": ", ".join(info.get("categories", [])) or "Unknown",
            "summary": info.get("description", ""),
            "cover_url": info.get("imageLinks", {}).get("thumbnail", "")
        }
    except:
        return None

# --------------------------------------------------
# DASHBOARD
# --------------------------------------------------
def dashboard():
    st.title("📊 Dashboard")

    total_books = db_query("SELECT COUNT(*) c FROM books")["c"][0]
    total_stock = db_query("SELECT SUM(stock) c FROM books")["c"][0] or 0
    out_stock = db_query("SELECT COUNT(*) c FROM books WHERE stock = 0")["c"][0]

    c1, c2, c3 = st.columns(3)
    c1.metric("Titles", total_books)
    c2.metric("Total Units", total_stock)
    c3.metric("Out of Stock", out_stock)

    st.subheader("Sales (Last 30 Days)")
    df = db_query("""
        SELECT sale_date, SUM(qty) qty
        FROM sales
        WHERE sale_date >= date('now','-30 days')
        GROUP BY sale_date
        ORDER BY sale_date
    """)
    if not df.empty:
        df["sale_date"] = pd.to_datetime(df["sale_date"]).dt.strftime("%Y-%m-%d")
        fig = px.bar(df, x="sale_date", y="qty")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No sales yet.")

# --------------------------------------------------
# INVENTORY
# --------------------------------------------------
def inventory():
    st.title("📚 Inventory")

    search = st.text_input("Search ISBN / Title")
    if search:
        df = db_query("SELECT * FROM books WHERE isbn LIKE ? OR title LIKE ?",
                      (f"%{search}%", f"%{search}%"))
    else:
        df = db_query("SELECT * FROM books ORDER BY created_at DESC")

    for _, row in df.iterrows():
        with st.expander(f"{row['title']} ({row['stock']} units)"):
            c1, c2 = st.columns([1, 4])
            with c1:
                if row["cover_url"]:
                    st.image(row["cover_url"], width=80)
            with c2:
                st.write("**Author:**", row["author"])
                st.write("**Genre:**", row["genre"])
                new_stock = st.number_input("Stock", value=int(row["stock"]), key=row["isbn"])
                if st.button("Update", key="u"+row["isbn"]):
                    db_execute("UPDATE books SET stock=? WHERE isbn=?",
                               (new_stock, row["isbn"]))
                    st.success("Updated")
                    st.rerun()

# --------------------------------------------------
# ADD BOOK
# --------------------------------------------------
def add_book():
    st.title("➕ Add Book")

    isbn = st.text_input("ISBN")
    if st.button("Fetch Metadata"):
        meta = fetch_book_metadata(isbn)
        if meta:
            st.session_state.meta = meta
        else:
            st.warning("Not found")

    meta = st.session_state.get("meta", {})
    title = st.text_input("Title", meta.get("title", ""))
    author = st.text_input("Author", meta.get("author", ""))
    genre = st.text_input("Genre", meta.get("genre", ""))
    summary = st.text_area("Summary", meta.get("summary", ""))
    mrp = st.number_input("MRP", 0.0)
    stock = st.number_input("Stock", 0)
    shelf = st.text_input("Shelf")

    if st.button("Save"):
        db_execute("""
            INSERT OR IGNORE INTO books
            (isbn,title,author,genre,summary,mrp,stock,shelf_location,cover_url)
            VALUES (?,?,?,?,?,?,?,?,?)
        """, (isbn, title, author, genre, summary, mrp, stock, shelf, meta.get("cover_url", "")))
        st.success("Saved")

# --------------------------------------------------
# SALES IMPORT
# --------------------------------------------------
def sales():
    st.title("🧾 Sales Import")

    file = st.file_uploader("Upload CSV/Excel", type=["csv", "xlsx"])
    if file:
        df = pd.read_csv(file) if file.name.endswith(".csv") else pd.read_excel(file)
        df.columns = [c.lower() for c in df.columns]
        if st.button("Process"):
            for _, r in df.iterrows():
                isbn = str(r["isbn"]).strip()
                qty = int(r["qty"])
                db_execute("INSERT INTO sales (isbn,qty,sale_date) VALUES (?,?,?)",
                           (isbn, qty, datetime.date.today()))
                db_execute("UPDATE books SET stock = max(stock-?,0) WHERE isbn=?",
                           (qty, isbn))
            st.success("Sales updated")

# --------------------------------------------------
# MAIN
# --------------------------------------------------
menu = st.sidebar.radio("Menu", ["Dashboard", "Inventory", "Add Book", "Sales"])

if menu == "Dashboard":
    dashboard()
elif menu == "Inventory":
    inventory()
elif menu == "Add Book":
    add_book()
elif menu == "Sales":
    sales()

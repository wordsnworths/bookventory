import streamlit as st
import sqlite3
import pandas as pd
import requests
import datetime
from io import BytesIO
import plotly.express as px

# Try to import streamlit-keyup for real-time search
try:
    from streamlit_keyup import st_keyup
except ImportError:
    st_keyup = None

# ==========================================
# 1. CONFIGURATION & STYLING
# ==========================================
st.set_page_config(
    page_title="Bookstore Inventory Pro",
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS
st.markdown("""
<style>
    .main .block-container { padding-top: 2rem; }
    .metric-card {
        background-color: #262730;
        border: 1px solid #3d3d3d;
        border-radius: 8px;
        padding: 20px;
        text-align: center;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
    }
    .metric-card h3 { color: #aaaaaa; font-size: 1rem; margin-bottom: 5px; }
    .metric-card h2 { color: #ffffff; font-size: 2rem; margin: 0; font-weight: 700; }
    .status-badge { padding: 4px 8px; border-radius: 4px; font-size: 0.8rem; font-weight: 600; }
    .badge-success { background-color: #1b5e20; color: #e8f5e9; }
    .badge-warning { background-color: #f57f17; color: #fff3e0; }
    .badge-danger { background-color: #b71c1c; color: #ffebee; }
    .badge-info { background-color: #0d47a1; color: #e3f2fd; }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 2. DATABASE MANAGEMENT
# ==========================================
class DBManager:
    def __init__(self, db_name="bookstore.db"):
        self.conn = sqlite3.connect(db_name, check_same_thread=False)
        self.create_tables()
        self.migrate_tables()

    def create_tables(self):
        c = self.conn.cursor()
        
        # Books Table - Added genre and summary
        c.execute('''CREATE TABLE IF NOT EXISTS books (
            isbn TEXT PRIMARY KEY,
            title TEXT,
            author TEXT,
            publisher TEXT,
            genre TEXT,
            summary TEXT,
            mrp REAL,
            stock INTEGER DEFAULT 0,
            shelf_location TEXT,
            purchase_date DATE,
            distributor_id INTEGER,
            cover_url TEXT,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')

        # Distributors Table
        c.execute('''CREATE TABLE IF NOT EXISTS distributors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            email TEXT,
            email_cc TEXT,
            return_window_months INTEGER DEFAULT 6
        )''')

        # Sales History
        c.execute('''CREATE TABLE IF NOT EXISTS sales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            isbn TEXT,
            qty INTEGER,
            sale_date DATE,
            FOREIGN KEY(isbn) REFERENCES books(isbn)
        )''')
        
        # Distributor Stock Lists
        c.execute('''CREATE TABLE IF NOT EXISTS distributor_catalog (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            distributor_id INTEGER,
            isbn TEXT,
            title TEXT,
            author TEXT,
            publisher TEXT,
            mrp REAL,
            qty_available INTEGER,
            last_updated DATE
        )''')

        self.conn.commit()

    def migrate_tables(self):
        c = self.conn.cursor()
        # Check if email_cc exists in distributors
        try:
            c.execute("SELECT email_cc FROM distributors LIMIT 1")
        except sqlite3.OperationalError:
            c.execute("ALTER TABLE distributors ADD COLUMN email_cc TEXT")
            self.conn.commit()

        # Check if publisher exists in distributor_catalog
        try:
            c.execute("SELECT publisher FROM distributor_catalog LIMIT 1")
        except sqlite3.OperationalError:
            c.execute("ALTER TABLE distributor_catalog ADD COLUMN publisher TEXT")
            self.conn.commit()
            
        # Check if genre and summary exist in books
        try:
            c.execute("SELECT genre FROM books LIMIT 1")
        except sqlite3.OperationalError:
            c.execute("ALTER TABLE books ADD COLUMN genre TEXT")
            c.execute("ALTER TABLE books ADD COLUMN summary TEXT")
            self.conn.commit()

    def query(self, query, params=()):
        return pd.read_sql(query, self.conn, params=params)

    def execute(self, query, params=()):
        c = self.conn.cursor()
        try:
            c.execute(query, params)
            self.conn.commit()
            return True
        except Exception as e:
            st.error(f"Database Error: {e}")
            return False

    def executemany(self, query, params_list):
        c = self.conn.cursor()
        try:
            c.executemany(query, params_list)
            self.conn.commit()
            return True
        except Exception as e:
            st.error(f"Database Error: {e}")
            return False

db = DBManager()

# ==========================================
# 3. HELPER FUNCTIONS
# ==========================================
def fetch_book_metadata(isbn):
    """
    Fetches book metadata. 
    Strategy: 
    1. Try Google Books API.
    2. If fails/empty, Try Open Library API.
    """
    clean_isbn = str(isbn).strip().replace("-", "")
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    # --- Attempt 1: Google Books ---
    try:
        url = f"https://www.googleapis.com/books/v1/volumes?q=isbn:{clean_isbn}"
        response = requests.get(url, headers=headers, timeout=5)
        
        if response.status_code == 200:
            data = response.json()
            if "items" in data and len(data["items"]) > 0:
                info = data["items"][0]["volumeInfo"]
                categories = info.get("categories", [])
                genre = ", ".join(categories) if categories else ""
                
                return {
                    "title": info.get("title", "Unknown"),
                    "author": ", ".join(info.get("authors", ["Unknown"])),
                    "publisher": info.get("publisher", "Unknown"),
                    "description": info.get("description", ""),
                    "genre": genre,
                    "cover_url": info.get("imageLinks", {}).get("thumbnail", "")
                }
    except Exception:
        pass 

    # --- Attempt 2: Open Library ---
    try:
        url = f"https://openlibrary.org/api/books?bibkeys=ISBN:{clean_isbn}&jscmd=data&format=json"
        response = requests.get(url, headers=headers, timeout=5)
        if response.status_code == 200:
            data = response.json()
            key = f"ISBN:{clean_isbn}"
            if key in data:
                info = data[key]
                authors = ", ".join([a['name'] for a in info.get('authors', [{'name': 'Unknown'}])])
                publishers = ", ".join([p['name'] for p in info.get('publishers', [{'name': 'Unknown'}])])
                
                subjects = info.get('subjects', [])
                genre_list = [s['name'] for s in subjects[:3]] 
                genre = ", ".join(genre_list)
                
                return {
                    "title": info.get("title", "Unknown"),
                    "author": authors,
                    "publisher": publishers,
                    "description": f"Published by {publishers}",
                    "genre": genre,
                    "cover_url": info.get("cover", {}).get("medium", "")
                }
    except Exception:
        pass

    return None

def calculate_status(row):
    status_badges = []
    try:
        stock_val = int(row['stock'])
    except:
        stock_val = 0

    if stock_val == 0:
        status_badges.append('<span class="status-badge badge-danger">Out of Stock</span>')
    elif stock_val < 3:
        status_badges.append('<span class="status-badge badge-warning">Low Stock</span>')
    
    sales = row.get('total_sales')
    if sales and sales >= 5:
        status_badges.append('<span class="status-badge badge-success">Bestseller</span>')
        
    return " ".join(status_badges) if status_badges else '<span class="status-badge badge-info">Active</span>'

# ==========================================
# 4. MODULES
# ==========================================

# --- DASHBOARD ---
def render_dashboard():
    st.title("Dashboard")
    col1, col2, col3, col4 = st.columns(4)
    
    total_books = db.query("SELECT COUNT(*) as c FROM books")['c'][0]
    total_stock = db.query("SELECT SUM(CAST(stock AS INTEGER)) as c FROM books")['c'][0]
    low_stock = db.query("SELECT COUNT(*) as c FROM books WHERE CAST(stock AS INTEGER) < 3 AND CAST(stock AS INTEGER) > 0")['c'][0]
    out_of_stock = db.query("SELECT COUNT(*) as c FROM books WHERE CAST(stock AS INTEGER) = 0")['c'][0]

    with col1: st.markdown(f'<div class="metric-card"><h3>Total Titles</h3><h2>{total_books}</h2></div>', unsafe_allow_html=True)
    with col2: st.markdown(f'<div class="metric-card"><h3>Total Units</h3><h2>{total_stock or 0}</h2></div>', unsafe_allow_html=True)
    with col3: st.markdown(f'<div class="metric-card"><h3>Low Stock</h3><h2>{low_stock}</h2></div>', unsafe_allow_html=True)
    with col4: st.markdown(f'<div class="metric-card"><h3>Out of Stock</h3><h2>{out_of_stock}</h2></div>', unsafe_allow_html=True)

    st.markdown("---")
    st.subheader("Sales Trend (Last 30 Days)")
    sales_data = db.query("SELECT sale_date, SUM(qty) as total_qty FROM sales WHERE sale_date >= date('now', '-30 days') GROUP BY sale_date ORDER BY sale_date ASC")
    if not sales_data.empty:
        sales_data['sale_date'] = pd.to_datetime(sales_data['sale_date']).dt.strftime('%Y-%m-%d')
        fig = px.bar(sales_data, x='sale_date', y='total_qty', template="plotly_dark")
        fig.update_xaxes(type='category')
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No sales data recorded recently.")

# --- INVENTORY (OPTIMIZED WITH PAGINATION) ---
def render_inventory():
    st.title("Inventory Management")
    tab1, tab2 = st.tabs(["Search & Edit", "Add New Book"])
    
    distributors = db.query("SELECT id, name FROM distributors")
    dist_map = dict(zip(distributors['name'], distributors['id'])) if not distributors.empty else {}

    with tab1:
        # Initialize pagination state
        if 'page' not in st.session_state:
            st.session_state.page = 0
        
        PAGE_SIZE = 50

        # Search Bar
        label = "Search Inventory (ISBN, Title)"
        if st_keyup:
            search = st_keyup(label, placeholder="Type to filter (Real-time)", key="inv_search", debounce=300)
        else:
            search = st.text_input(label, placeholder="Type to search (Press Enter)", key="inv_search")
            st.caption("ℹ️ Install `streamlit-keyup` in terminal (`pip install streamlit-keyup`) for instant search-as-you-type.")

        # Query Construction
        base_query = """
            SELECT b.*, d.name as distributor_name, 
            (SELECT SUM(qty) FROM sales WHERE isbn = b.isbn) as total_sales
            FROM books b 
            LEFT JOIN distributors d ON b.distributor_id = d.id
        """
        
        if search:
            # If searching, show all matches (usually small number)
            query = f"{base_query} WHERE b.isbn LIKE ? OR b.title LIKE ?"
            df = db.query(query, (f'%{search}%', f'%{search}%'))
            # Reset page when searching
            st.session_state.page = 0
        else:
            # If NOT searching, use Pagination (LIMIT/OFFSET)
            offset = st.session_state.page * PAGE_SIZE
            query = f"{base_query} ORDER BY b.added_at DESC LIMIT {PAGE_SIZE} OFFSET {offset}"
            df = db.query(query)

        # Count Total for Pagination Controls (Only if not searching)
        total_rows = 0
        if not search:
            total_rows = db.query("SELECT COUNT(*) as c FROM books")['c'][0]

        # Display Logic
        if not df.empty:
            # Force stock to int
            df['stock'] = pd.to_numeric(df['stock'], errors='coerce').fillna(0).astype(int)
            
            for _, row in df.iterrows():
                with st.expander(f"{row['title']} ({row['stock']} in stock)"):
                    c1, c2, c3 = st.columns([1, 3, 2])
                    with c1:
                        if row['cover_url']: st.image(row['cover_url'], width=80)
                    with c2:
                        st.markdown(f"**Author:** {row['author']} | **Shelf:** `{row['shelf_location']}`")
                        st.markdown(f"**Genre:** {row.get('genre', 'Unknown')}")
                        st.markdown(f"**Distributor:** {row['distributor_name']}")
                        if row.get('summary'):
                            with st.expander("Summary"):
                                st.caption(row['summary'])
                        st.markdown(calculate_status(row), unsafe_allow_html=True)
                    with c3:
                        with st.form(f"edit_{row['isbn']}"):
                            n_stock = st.number_input("Stock", value=int(row['stock']), key=f"s_{row['isbn']}")
                            n_shelf = st.text_input("Shelf", value=row['shelf_location'], key=f"sh_{row['isbn']}")
                            
                            col_up, col_del = st.columns(2)
                            with col_up:
                                if st.form_submit_button("Update", type="primary"):
                                    db.execute("UPDATE books SET stock = ?, shelf_location = ? WHERE isbn = ?", (n_stock, n_shelf, row['isbn']))
                                    st.rerun()
                            with col_del:
                                if st.form_submit_button("Delete Book", type="secondary"):
                                    db.execute("DELETE FROM books WHERE isbn = ?", (row['isbn'],))
                                    st.warning(f"Deleted {row['title']}")
                                    st.rerun()
                        
                        if st.button("Add to Order Cart", key=f"cart_{row['isbn']}"):
                            if 'cart' not in st.session_state: st.session_state.cart = {}
                            st.session_state.cart[row['isbn']] = {
                                'title': row['title'], 'author': row['author'],
                                'distributor': row['distributor_name'], 'qty': st.session_state.cart.get(row['isbn'], {}).get('qty', 0) + 1
                            }
                            st.success("Added to cart")
            
            # Pagination Controls
            if not search and total_rows > PAGE_SIZE:
                st.markdown("---")
                col_p1, col_p2, col_p3 = st.columns([1, 2, 1])
                with col_p1:
                    if st.session_state.page > 0:
                        if st.button("Previous Page"):
                            st.session_state.page -= 1
                            st.rerun()
                with col_p2:
                    st.write(f"Page {st.session_state.page + 1} of {(total_rows // PAGE_SIZE) + 1}")
                with col_p3:
                    if (st.session_state.page + 1) * PAGE_SIZE < total_rows:
                        if st.button("Next Page"):
                            st.session_state.page += 1
                            st.rerun()

        else:
            if search:
                st.info("No books found matching your search.")
            else:
                st.info("Inventory is empty. Add books in the next tab.")

    with tab2:
        st.subheader("Single Entry")
        c1, c2 = st.columns([1, 3])
        with c1:
            isbn_in = st.text_input("ISBN")
            if st.button("Fetch Metadata"):
                meta = fetch_book_metadata(isbn_in)
                if meta: st.session_state.new_meta = meta
                else: st.warning("Not found")
        
        meta = st.session_state.get('new_meta', {})
        
        if not dist_map:
            st.error("⚠️ No Distributors Found! Please go to the 'Distributors' tab and add at least one distributor before adding books.")
        else:
            with st.form("add_book"):
                title = st.text_input("Title", value=meta.get('title', ''))
                author = st.text_input("Author", value=meta.get('author', ''))
                genre = st.text_input("Genre", value=meta.get('genre', ''))
                summary = st.text_area("Summary", value=meta.get('description', ''))
                dist = st.selectbox("Distributor", options=list(dist_map.keys()))
                mrp = st.number_input("MRP", 0.0)
                stock = st.number_input("Stock", 0)
                shelf = st.text_input("Shelf Location")
                f_isbn = isbn_in if isbn_in else ""
                
                if st.form_submit_button("Save Book"):
                    if title and dist and f_isbn:
                        db.execute("INSERT OR REPLACE INTO books (isbn, title, author, genre, summary, mrp, stock, shelf_location, distributor_id, cover_url, purchase_date) VALUES (?,?,?,?,?,?,?,?,?,?,?)", 
                                   (f_isbn, title, author, genre, summary, mrp, stock, shelf, dist_map[dist], meta.get('cover_url', ''), datetime.date.today()))
                        st.success("Saved!")
                    else:
                        st.error("Error: ISBN, Title, and Distributor are required.")
        
        st.markdown("---")
        st.subheader("Bulk Import Books")
        st.info("Upload CSV/Excel with columns: `ISBN`. Optional: `Stock`, `Shelf`, `Distributor`.")
        st.markdown("**Note:** If Title/Author are missing, the system will try to auto-fetch them from the web.")
        
        bulk_file = st.file_uploader("Upload Books File", type=['csv', 'xlsx'], key="bulk_book_upload")
        
        if bulk_file and st.button("Process Bulk Import"):
            try:
                if bulk_file.name.endswith('.csv'):
                    df_bulk = pd.read_csv(bulk_file)
                else:
                    df_bulk = pd.read_excel(bulk_file)
                
                df_bulk.columns = [c.lower().strip() for c in df_bulk.columns]
                
                count_added = 0
                total_rows = len(df_bulk)
                progress_bar = st.progress(0)
                status_text = st.empty()
                
                for idx, row in df_bulk.iterrows():
                    progress_bar.progress(min((idx + 1) / total_rows, 1.0))
                    b_isbn = str(row.get('isbn', '')).strip()
                    if not b_isbn: continue
                    
                    has_title = 'title' in row and pd.notna(row['title']) and str(row['title']).strip() != ''
                    has_author = 'author' in row and pd.notna(row['author']) and str(row['author']).strip() != ''
                    
                    b_title = row['title'] if has_title else None
                    b_author = row['author'] if has_author else None
                    b_genre = row.get('genre', '')
                    b_summary = row.get('summary', '')
                    b_cover = ''
                    
                    if not b_title or not b_author:
                        status_text.text(f"Fetching metadata for {b_isbn}...")
                        meta = fetch_book_metadata(b_isbn)
                        if meta:
                            if not b_title: b_title = meta['title']
                            if not b_author: b_author = meta['author']
                            if not b_genre: b_genre = meta['genre']
                            if not b_summary: b_summary = meta['description']
                            b_cover = meta.get('cover_url', '')
                    
                    if not b_title: b_title = f"Unknown Title ({b_isbn})"
                    if not b_author: b_author = "Unknown"
                    if not b_genre: b_genre = "Unknown"
                    
                    b_mrp = row.get('mrp', 0.0)
                    b_stock = row.get('stock', 0)
                    b_shelf = row.get('shelf', '')
                    b_dist_name = row.get('distributor', '')
                    b_dist_id = dist_map.get(b_dist_name, None)
                    
                    try:
                        db.execute('''INSERT OR IGNORE INTO books 
                        (isbn, title, author, genre, summary, mrp, stock, shelf_location, distributor_id, purchase_date, cover_url)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''', 
                        (b_isbn, b_title, b_author, b_genre, b_summary, b_mrp, b_stock, b_shelf, b_dist_id, datetime.date.today(), b_cover))
                        count_added += 1
                    except Exception:
                        pass
                
                status_text.text("Done!")
                progress_bar.progress(100)
                st.success(f"Processed file. Added/Checked {count_added} books.")
            except Exception as e:
                st.error(f"Error processing file: {e}")

# --- DISTRIBUTORS ---
def render_distributors():
    st.title("Distributor Ecosystem")
    dist_df = db.query("SELECT * FROM distributors")
    dist_map = dict(zip(dist_df['name'], dist_df['id'])) if not dist_df.empty else {}

    tab1, tab2, tab3, tab4 = st.tabs(["Distributor List (Edit/Delete)", "Add Distributor", "Upload Stock List", "Browse & Order"])
    
    with tab1:
        if not dist_df.empty:
            for _, row in dist_df.iterrows():
                with st.expander(f"{row['name']}"):
                    with st.form(f"edit_dist_{row['id']}"):
                        c1, c2 = st.columns(2)
                        with c1:
                            e_name = st.text_input("Name", value=row['name'])
                            e_win = st.number_input("Return Window (Months)", value=row['return_window_months'])
                        with c2:
                            e_email = st.text_input("Email(s) (comma separated)", value=row['email'])
                            e_cc = st.text_input("CC Email(s)", value=row.get('email_cc') or "")
                        
                        btn_col1, btn_col2 = st.columns(2)
                        with btn_col1:
                            if st.form_submit_button("Update Details"):
                                db.execute("UPDATE distributors SET name=?, email=?, email_cc=?, return_window_months=? WHERE id=?", 
                                           (e_name, e_email, e_cc, e_win, row['id']))
                                st.success("Updated!")
                                st.rerun()
                        with btn_col2:
                            if st.form_submit_button("Delete Distributor"):
                                db.execute("DELETE FROM distributors WHERE id=?", (row['id'],))
                                st.warning("Deleted!")
                                st.rerun()
        else:
            st.info("No distributors found.")
    
    with tab2:
        with st.form("new_dist"):
            st.write("### Add New Distributor")
            name = st.text_input("Name")
            email = st.text_input("Email(s) (comma separated)")
            email_cc = st.text_input("CC Email(s) (comma separated)")
            window = st.number_input("Return Window (Months)", value=6)
            
            if st.form_submit_button("Save Distributor"):
                db.execute("INSERT INTO distributors (name, email, email_cc, return_window_months) VALUES (?, ?, ?, ?)", 
                           (name, email, email_cc, window))
                st.success("Added!")
                st.rerun()

    with tab3:
        st.subheader("Import Distributor Stock List")
        if not dist_map:
            st.warning("Please add a distributor first.")
        else:
            sel_dist = st.selectbox("Select Distributor", list(dist_map.keys()))
            up_file = st.file_uploader("Upload CSV/Excel", type=['csv', 'xlsx'])
            
            st.markdown("""
            **Note:** - Uploading a new file will **REPLACE** the existing stock list for this distributor.
            - File must have columns: `ISBN`, `Title`, `Author` (opt), `Publisher` (opt), `MRP` (opt), `Qty` (opt).
            """)
            
            if up_file and st.button("Process Upload"):
                try:
                    df = pd.read_csv(up_file) if up_file.name.endswith('.csv') else pd.read_excel(up_file)
                    df.columns = [c.lower().strip() for c in df.columns] # Normalize headers
                    
                    dist_id = dist_map[sel_dist]
                    
                    # Clear old catalog for this distributor
                    db.execute("DELETE FROM distributor_catalog WHERE distributor_id = ?", (dist_id,))
                    
                    data_batch = []
                    
                    for _, row in df.iterrows():
                        isbn = row.get('isbn', row.get('id', ''))
                        title = row.get('title', row.get('name', 'Unknown'))
                        author = row.get('author', row.get('writer', 'Unknown'))
                        publisher = row.get('publisher', row.get('pub', 'Unknown'))
                        mrp = row.get('mrp', row.get('price', 0))
                        qty = row.get('qty', row.get('stock', 0))
                        
                        if isbn:
                            data_batch.append((dist_id, str(isbn), title, author, publisher, mrp, qty, datetime.date.today()))
                    
                    if data_batch:
                        db.executemany('''INSERT INTO distributor_catalog 
                            (distributor_id, isbn, title, author, publisher, mrp, qty_available, last_updated)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)''', data_batch)
                        
                        st.success(f"Successfully imported {len(data_batch)} items for {sel_dist}!")
                    else:
                        st.warning("No valid ISBNs found.")
                        
                except Exception as e:
                    st.error(f"Error processing file: {e}")

    with tab4:
        st.subheader("Order from Distributor Catalogs")
        label = "Search Catalog (ISBN, Title, Publisher)"
        if st_keyup:
            search_cat = st_keyup(label, placeholder="Type to filter (Real-time)", key="cat_search", debounce=300)
        else:
            search_cat = st.text_input(label, key="cat_search")
            st.caption("ℹ️ Install `streamlit-keyup` in terminal (`pip install streamlit-keyup`) for instant search-as-you-type.")
        
        query = """
            SELECT dc.*, d.name as dist_name 
            FROM distributor_catalog dc 
            JOIN distributors d ON dc.distributor_id = d.id
        """
        if search_cat:
            query += f" WHERE dc.title LIKE '%{search_cat}%' OR dc.isbn LIKE '%{search_cat}%' OR dc.publisher LIKE '%{search_cat}%'"
        
        cat_results = db.query(query + " LIMIT 50")
        
        if not cat_results.empty:
            for _, row in cat_results.iterrows():
                col1, col2, col3 = st.columns([3, 1, 1])
                with col1:
                    st.markdown(f"**{row['title']}**")
                    st.caption(f"ISBN: {row['isbn']} | Author: {row['author']}")
                    st.caption(f"**Publisher:** {row['publisher']} | **Distributor:** {row['dist_name']}")
                with col2:
                    st.write(f"**MRP:** {row['mrp']}")
                    if row['qty_available'] > 0:
                        st.markdown(f"<span style='color:#4caf50; font-weight:bold'>Stock: {row['qty_available']}</span>", unsafe_allow_html=True)
                    else:
                        st.markdown(f"<span style='color:#f44336; font-weight:bold'>Out of Stock</span>", unsafe_allow_html=True)
                with col3:
                    qty_add = st.number_input("Qty", min_value=1, value=1, step=1, key=f"qty_{row['id']}", label_visibility="collapsed")
                    
                    if st.button("Add", key=f"cat_add_{row['id']}"):
                        if 'cart' not in st.session_state: st.session_state.cart = {}
                        
                        curr = st.session_state.cart.get(row['isbn'], {}).get('qty', 0)
                        st.session_state.cart[row['isbn']] = {
                            'title': row['title'],
                            'author': row['author'] if row['author'] else 'Unknown',
                            'distributor': row['dist_name'],
                            'qty': curr + qty_add
                        }
                        st.toast(f"Added {qty_add} x {row['title']} to cart!")
        else:
            st.info("No items found.")

# --- ORDERING ---
def render_orders():
    st.title("Order Cart")
    
    if 'cart' not in st.session_state or not st.session_state.cart:
        st.info("Cart is empty.")
        return

    cart_data = []
    for isbn, item in st.session_state.cart.items():
        cart_data.append({
            "ISBN": isbn, "Title": item['title'], 
            "Distributor": item['distributor'], "Qty": item['qty']
        })
    
    df = pd.DataFrame(cart_data)
    edited_df = st.data_editor(df, num_rows="dynamic", key="cart_edit")
    
    st.markdown("### Actions")
    if st.button("Generate Distributor Emails & Excel"):
        grouped = edited_df.groupby("Distributor")
        
        dist_info = db.query("SELECT name, email, email_cc FROM distributors")
        email_map = {}
        if not dist_info.empty:
            for _, r in dist_info.iterrows():
                email_map[r['name']] = {'to': r['email'], 'cc': r['email_cc']}

        for dist_name, group in grouped:
            with st.expander(f"Order for {dist_name}", expanded=True):
                st.dataframe(group)
                
                d_emails = email_map.get(dist_name, {'to': '', 'cc': ''})
                
                output = BytesIO()
                with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                    group.to_excel(writer, index=False)
                
                st.download_button(f"Download Excel ({dist_name})", output.getvalue(), f"Order_{dist_name}.xlsx")
                
                email_header = f"To: {d_emails['to']}\nCC: {d_emails['cc']}\nSubject: New Order - Bookstore\n\n"
                email_body = f"Dear {dist_name},\n\nPlease ship the following:\n\n{group[['Title','Qty']].to_string(index=False)}"
                
                st.text_area("Email Draft", value=email_header + email_body, height=200)

    if st.button("Clear Cart"):
        st.session_state.cart = {}
        st.rerun()

# --- SALES IMPORT ---
def render_sales_import():
    st.title("Import Sales")
    up = st.file_uploader("Upload Sales Report (CSV/Excel)", type=['csv', 'xlsx'])
    if up:
        try:
            if up.name.endswith('.csv'):
                df = pd.read_csv(up)
            else:
                df = pd.read_excel(up)
            
            df.columns = [c.lower().strip() for c in df.columns]
            
            st.write("Preview:", df.head())
            if st.button("Process Sales"):
                if 'isbn' in df.columns and 'qty' in df.columns:
                    df['qty'] = pd.to_numeric(df['qty'], errors='coerce').fillna(0).astype(int)
                    
                    progress_bar = st.progress(0)
                    total_sales = len(df)
                    
                    for idx, row in df.iterrows():
                        progress_bar.progress(min((idx + 1) / total_sales, 1.0))
                        row_isbn = str(row['isbn']).strip()
                        
                        if db.query("SELECT 1 FROM books WHERE isbn = ?", (row_isbn,)).empty:
                            meta = fetch_book_metadata(row_isbn)
                            if meta:
                                new_title = meta['title']
                                new_author = meta['author']
                                new_genre = meta['genre']
                                new_summary = meta['description']
                                new_cover = meta.get('cover_url', '')
                            else:
                                new_title = f"Unknown Title ({row_isbn})"
                                new_author = "Unknown"
                                new_genre = "Unknown"
                                new_summary = ""
                                new_cover = ""
                            
                            db.execute("INSERT INTO books (isbn, title, stock, author, genre, summary, cover_url) VALUES (?, ?, ?, ?, ?, ?, ?)", 
                                       (row_isbn, new_title, 0, new_author, new_genre, new_summary, new_cover))
                            st.toast(f"ℹ️ Auto-created book entry for ISBN: {row_isbn}")
                        
                        db.execute("INSERT INTO sales (isbn, qty, sale_date) VALUES (?, ?, ?)", 
                                   (row_isbn, row['qty'], datetime.date.today()))
                        
                        curr = db.query("SELECT stock FROM books WHERE isbn = ?", (row_isbn,))
                        if not curr.empty:
                            try:
                                curr_stock = int(curr.iloc[0]['stock'])
                            except:
                                curr_stock = 0
                            
                            new_stock = max(0, curr_stock - row['qty'])
                            db.execute("UPDATE books SET stock = ? WHERE isbn = ?", (new_stock, row_isbn))
                    
                    progress_bar.progress(100)
                    st.success("Sales Imported!")
                else:
                    st.error("CSV/Excel must have 'isbn' and 'qty' columns")
        except Exception as e:
            st.error(f"Error reading file: {e}")

# --- RETURNS ---
def render_returns():
    st.title("Returns Due")
    q = """SELECT b.title, b.stock, d.name as dist, 
           date(b.purchase_date, '+' || d.return_window_months || ' months') as due_date 
           FROM books b JOIN distributors d ON b.distributor_id = d.id WHERE b.stock > 0"""
    df = db.query(q)
    if not df.empty:
        df['due_date'] = pd.to_datetime(df['due_date'])
        df['days_left'] = (df['due_date'] - pd.to_datetime(datetime.date.today())).dt.days
        df['due_date'] = df['due_date'].dt.strftime('%Y-%m-%d')
        st.dataframe(df.style.map(lambda x: 'color: red' if x < 0 else 'color: orange' if x < 30 else 'color: white', subset=['days_left']))
    else:
        st.info("No returns pending.")

# --- RECEIVING ---
def render_receiving():
    st.title("Receiving")
    
    tab1, tab2 = st.tabs(["Quick Scan", "Bulk Upload"])
    
    with tab1:
        isbn = st.text_input("Scan ISBN")
        qty = st.number_input("Qty Received", 1)
        if st.button("Add Stock"):
            if isbn:
                if db.query("SELECT 1 FROM books WHERE isbn = ?", (isbn,)).empty:
                    meta = fetch_book_metadata(isbn)
                    if meta:
                        new_title = meta['title']
                        new_author = meta['author']
                        new_genre = meta['genre']
                        new_summary = meta['description']
                        new_cover = meta.get('cover_url', '')
                    else:
                        new_title = f"Unknown Title ({isbn})"
                        new_author = "Unknown"
                        new_genre = "Unknown"
                        new_summary = ""
                        new_cover = ""
                    
                    db.execute("INSERT INTO books (isbn, title, stock, author, genre, summary, cover_url) VALUES (?, ?, ?, ?, ?, ?, ?)", 
                                (isbn, new_title, 0, new_author, new_genre, new_summary, new_cover))
                    st.toast(f"ℹ️ Auto-created book entry for ISBN: {isbn}")
                
                db.execute("UPDATE books SET stock = stock + ? WHERE isbn = ?", (qty, isbn))
                st.success("Stock Updated")
            else:
                st.error("Please enter an ISBN")

    with tab2:
        st.subheader("Bulk Receiving")
        up_recv = st.file_uploader("Upload Receiving List (CSV/Excel)", type=['csv', 'xlsx'], key="recv_up")
        
        st.info("File must contain: `ISBN` and `Qty`. New books will be auto-created with metadata from web.")
        
        if up_recv and st.button("Process Receiving"):
            try:
                if up_recv.name.endswith('.csv'):
                    df = pd.read_csv(up_recv)
                else:
                    df = pd.read_excel(up_recv)
                
                df.columns = [c.lower().strip() for c in df.columns]
                
                if 'isbn' in df.columns and 'qty' in df.columns:
                    df['qty'] = pd.to_numeric(df['qty'], errors='coerce').fillna(0).astype(int)
                    
                    progress_bar = st.progress(0)
                    total_rows = len(df)
                    status_text = st.empty()
                    
                    for idx, row in df.iterrows():
                        progress_bar.progress(min((idx + 1) / total_rows, 1.0))
                        row_isbn = str(row['isbn']).strip()
                        if not row_isbn: continue
                        
                        if db.query("SELECT 1 FROM books WHERE isbn = ?", (row_isbn,)).empty:
                            status_text.text(f"Fetching metadata for new book: {row_isbn}...")
                            meta = fetch_book_metadata(row_isbn)
                            if meta:
                                new_title = meta['title']
                                new_author = meta['author']
                                new_genre = meta['genre']
                                new_summary = meta['description']
                                new_cover = meta.get('cover_url', '')
                            else:
                                new_title = f"Unknown Title ({row_isbn})"
                                new_author = "Unknown"
                                new_genre = "Unknown"
                                new_summary = ""
                                new_cover = ""
                            
                            db.execute("INSERT INTO books (isbn, title, stock, author, genre, summary, cover_url) VALUES (?, ?, ?, ?, ?, ?, ?)", 
                                       (row_isbn, new_title, 0, new_author, new_genre, new_summary, new_cover))
                        
                        db.execute("UPDATE books SET stock = stock + ? WHERE isbn = ?", (row['qty'], row_isbn))
                    
                    status_text.text("Done!")
                    progress_bar.progress(100)
                    st.success(f"Stock Received Successfully! Processed {total_rows} items.")
                else:
                    st.error("File must have 'isbn' and 'qty' columns.")
            except Exception as e:
                st.error(f"Error reading file: {e}")

# --- MAIN ---
def main():
    with st.sidebar:
        st.title("📚 BookPro")
        choice = st.radio("Menu", ["Dashboard", "Inventory", "Ordering", "Sales Import", "Returns", "Distributors", "Receiving"])
    
    if choice == "Dashboard": render_dashboard()
    elif choice == "Inventory": render_inventory()
    elif choice == "Ordering": render_orders()
    elif choice == "Sales Import": render_sales_import()
    elif choice == "Returns": render_returns()
    elif choice == "Distributors": render_distributors()
    elif choice == "Receiving": render_receiving()

if __name__ == "__main__":
    main()

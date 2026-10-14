from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
import sqlite3
import os
from datetime import datetime, timezone, timedelta
from google import genai
from google.genai import types
import json
import re

app = Flask(__name__)
app.secret_key = 'mfs_pos_secret_key_prime'

DB_NAME = 'pos_database.db'

# Myanmar Standard Time (UTC+6:30)
MMT = timezone(timedelta(hours=6, minutes=30))

# Gemini Client Initialization (Environment variable မှ API Key ကို ယူပါမည်)
client = genai.Client()

def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shop_name TEXT NOT NULL,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            txn_type TEXT NOT NULL,
            customer_phone TEXT,
            own_account TEXT,
            txn_id TEXT,
            amount REAL NOT NULL,
            commission REAL NOT NULL,
            timestamp TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    
    cursor.execute("PRAGMA table_info(transactions)")
    columns = [col[1] for col in cursor.fetchall()]
    if 'own_account' not in columns:
        cursor.execute("ALTER TABLE transactions ADD COLUMN own_account TEXT")
    if 'txn_id' not in columns:
        cursor.execute("ALTER TABLE transactions ADD COLUMN txn_id TEXT")
        
    conn.commit()
    conn.close()

init_db()

def get_mmt_now():
    return datetime.now(MMT)

@app.route('/')
def home():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        shop_name = request.form['shop_name']
        username = request.form['username']
        password = request.form['password']
        
        conn = get_db()
        cursor = conn.cursor()
        try:
            cursor.execute('INSERT INTO users (shop_name, username, password) VALUES (?, ?, ?)',
                           (shop_name, username, password))
            conn.commit()
            flash('အကောင့်သစ် အောင်မြင်စွာ ဖွင့်ပြီးပါပြီ! လော့ဂ်အင် ဝင်ပါ။', 'success')
            return redirect(url_for('home'))
        except sqlite3.IntegrityError:
            flash('ဒီ အသုံးပြုသူအမည် (Username) ယူထားပြီးသား ဖြစ်နေပါတယ်။', 'danger')
        finally:
            conn.close()
    return render_template('register.html')

@app.route('/login', methods=['POST'])
def login():
    username = request.form['username']
    password = request.form['password']
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM users WHERE username = ? AND password = ?', (username, password))
    user = cursor.fetchone()
    conn.close()
    
    if user:
        session['user_id'] = user['id']
        session['shop_name'] = user['shop_name']
        session['username'] = user['username']
        return redirect(url_for('dashboard'))
    else:
        flash('အသုံးပြုသူအမည် သို့မဟုတ် စကားဝှက် မှားယွင်းနေပါသည်။', 'danger')
        return redirect(url_for('home'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('home'))
    
    user_id = session['user_id']
    now_mmt = get_mmt_now()
    today_prefix = now_mmt.strftime('%Y-%m-%d')
    
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT 
            SUM(CASE WHEN txn_type = 'Cash In' THEN amount ELSE 0 END) as today_in,
            SUM(CASE WHEN txn_type = 'Cash Out' THEN amount ELSE 0 END) as today_out,
            SUM(commission) as today_comm
        FROM transactions
        WHERE user_id = ? AND timestamp LIKE ?
    ''', (user_id, f"{today_prefix}%"))
    summary = cursor.fetchone()
    
    today_in = summary['today_in'] or 0.0
    today_out = summary['today_out'] or 0.0
    today_comm = summary['today_comm'] or 0.0
    
    cursor.execute('''
        SELECT * FROM transactions 
        WHERE user_id = ? 
        ORDER BY id DESC LIMIT 20
    ''', (user_id,))
    recent_txns = cursor.fetchall()
    conn.close()
    
    return render_template('dashboard.html', 
                           shop_name=session['shop_name'],
                           username=session['username'],
                           today_in=today_in,
                           today_out=today_out,
                           today_comm=today_comm,
                           transactions=recent_txns,
                           today_date=today_prefix)

# --- GEMINI AI VISION OCR SCAN ROUTE ---
@app.route('/scan_receipt', methods=['POST'])
def scan_receipt():
    if 'user_id' not in session:
        return jsonify({'success': False, 'error': 'Unauthorized'})
    
    if 'file' not in request.files:
        return jsonify({'success': False, 'error': 'No file uploaded'})
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'success': False, 'error': 'Empty filename'})
        
    try:
        image_bytes = file.read()
        
        prompt = """
        Analyze this mobile banking payment slip (KBZPay, Wave Money, etc.) and extract two exact details:
        1. Amount (ငွေပမာဏ): only the number without commas or currency units (e.g., 15000).
        2. Transaction ID / Slip ID (လုပ်ဆောင်မှုအမှတ်): the long transaction number.
        
        Return ONLY a JSON response in this exact format, with no markdown code blocks or extra text:
        {"amount": "...", "txn_id": "..."}
        If any value is not found, leave it as an empty string "".
        """
        
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=[
                types.Part.from_bytes(
                    data=image_bytes,
                    mime_type=file.content_type or 'image/jpeg',
                ),
                prompt
            ]
        )
        
        res_text = response.text.strip()
        if res_text.startswith("```json"):
            res_text = res_text[7:]
        if res_text.endswith("```"):
            res_text = res_text[:-3]
        res_text = res_text.strip()
        
        data = json.loads(res_text)
        
        return jsonify({
            'success': True,
            'amount': data.get('amount', ''),
            'txn_id': data.get('txn_id', '')
        })
    except Exception as e:
        print("Gemini OCR Error:", str(e))
        return jsonify({'success': False, 'error': str(e)})

@app.route('/add_transaction', methods=['POST'])
def add_transaction():
    if 'user_id' not in session:
        return redirect(url_for('home'))
    
    user_id = session['user_id']
    txn_type = request.form['txn_type']
    customer_phone = request.form.get('customer_phone', '')
    own_account = request.form.get('own_account', 'Main Account')
    txn_id = request.form.get('txn_id', '')
    amount = float(request.form.get('amount', 0))
    comm_rate = float(request.form.get('commission_rate', 0))
    
    commission = (amount * comm_rate) / 100.0
    timestamp = get_mmt_now().strftime('%Y-%m-%d %H:%M:%S')
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO transactions (user_id, txn_type, customer_phone, own_account, txn_id, amount, commission, timestamp)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (user_id, txn_type, customer_phone, own_account, txn_id, amount, commission, timestamp))
    conn.commit()
    conn.close()
    
    flash('စာရင်းအသစ် အောင်မြင်စွာ ထည့်သွင်းပြီးပါပြီ။', 'success')
    return redirect(url_for('dashboard'))

@app.route('/history')
def history():
    if 'user_id' not in session:
        return redirect(url_for('home'))
    
    user_id = session['user_id']
    search_query = request.args.get('search', '')
    
    conn = get_db()
    cursor = conn.cursor()
    
    if search_query:
        cursor.execute('''
            SELECT * FROM transactions 
            WHERE user_id = ? AND (customer_phone LIKE ? OR own_account LIKE ? OR txn_id LIKE ? OR txn_type LIKE ?)
            ORDER BY id DESC
        ''', (user_id, f"%{search_query}%", f"%{search_query}%", f"%{search_query}%", f"%{search_query}%"))
    else:
        cursor.execute('SELECT * FROM transactions WHERE user_id = ? ORDER BY id DESC', (user_id,))
        
    all_txns = cursor.fetchall()
    conn.close()
    
    return render_template('history.html', transactions=all_txns, search_query=search_query)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
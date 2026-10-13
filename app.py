from flask import Flask, render_template_string, request, redirect, url_for, session
import os
from PIL import Image
import pytesseract
import re
import sqlite3
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash

pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

app = Flask(__name__)
app.secret_key = 'your_super_secret_key_here'
UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

def init_db():
    conn = sqlite3.connect('pos_database.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            shop_name TEXT NOT NULL
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shop_id INTEGER,
            tx_type TEXT,
            customer_phone TEXT,
            transaction_id TEXT,
            amount REAL,
            amount_str TEXT,
            fee_value REAL,
            fee TEXT,
            date_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(shop_id) REFERENCES users(id)
        )
    ''')
    conn.commit()
    conn.close()

init_db()

@app.route('/')
def index():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    current_shop_id = session['user_id']
    conn = sqlite3.connect('pos_database.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # ဤဆိုင်၏ မှတ်တမ်းများကို ထုတ်ယူခြင်း
    cursor.execute('SELECT tx_type, customer_phone, transaction_id, amount_str, fee, date_time FROM transactions WHERE shop_id = ? ORDER BY id DESC', (current_shop_id,))
    transactions = cursor.fetchall()
    
    # ယနေ့ (Today) နေ့စွဲဖြင့် စာရင်းချုပ်ရန်အတွက် တွက်ချက်ခြင်း
    today_date = datetime.now().strftime('%Y-%m-%d')
    cursor.execute('''
        SELECT tx_type, amount, fee_value 
        FROM transactions 
        WHERE shop_id = ? AND date(date_time) = ?
    ''', (current_shop_id, today_date))
    today_txs = cursor.fetchall()
    conn.close()
    
    # Summary တွက်ချက်ခြင်း
    total_cash_in = 0.0
    total_cash_out = 0.0
    total_commission = 0.0
    
    for tx in today_txs:
        if tx['tx_type'] == 'Cash In':
            total_cash_in += tx['amount'] if tx['amount'] else 0.0
        else:
            total_cash_out += tx['amount'] if tx['amount'] else 0.0
        total_commission += tx['fee_value'] if tx['fee_value'] else 0.0

    return render_template_string('''
    <!DOCTYPE html>
    <html lang="my">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>MFS POS - ဆိုင်ရှင် ဒက်ရှ်ဘုတ်</title>
        <style>
            body { font-family: sans-serif; background: #f4f7f6; margin: 0; padding: 20px; }
            .container { max-width: 1000px; margin: auto; background: white; padding: 25px; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
            h2 { color: #333; margin-top: 0; }
            .logout { float: right; background: #dc3545; color: white; padding: 8px 15px; text-decoration: none; border-radius: 4px; font-size: 0.9em; }
            
            /* Summary Cards Styling */
            .summary-cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 15px; margin-top: 20px; }
            .card { background: #fff; padding: 20px; border-radius: 8px; box-shadow: 0 2px 5px rgba(0,0,0,0.05); border-left: 5px solid #007bff; }
            .card.in { border-left-color: #28a745; }
            .card.out { border-left-color: #dc3545; }
            .card.commission { border-left-color: #ffc107; }
            .card h4 { margin: 0 0 10px 0; color: #666; font-size: 0.95em; }
            .card .value { font-size: 1.25em; font-weight: bold; color: #333; }

            .upload-box { background: #e9ecef; padding: 20px; border-radius: 6px; margin-top: 25px; }
            .form-group { margin-bottom: 15px; }
            label { display: block; margin-bottom: 5px; font-weight: bold; color: #555; }
            select, input[type="text"], input[type="file"] { width: 100%; padding: 10px; border: 1px solid #ccc; border-radius: 4px; box-sizing: border-box; }
            button { background: #28a745; color: white; border: none; padding: 12px 20px; border-radius: 4px; cursor: pointer; font-size: 1em; width: 100%; }
            button:hover { background: #218838; }
            table { width: 100%; border-collapse: collapse; margin-top: 20px; }
            th, td { border: 1px solid #ddd; padding: 10px; text-align: left; font-size: 0.95em; }
            th { background-color: #007bff; color: white; }
            tr:nth-child(even) { background-color: #f9f9f9; }
            .badge-in { background: #d4edda; color: #155724; padding: 4px 8px; border-radius: 4px; font-weight: bold; }
            .badge-out { background: #f8d7da; color: #721c24; padding: 4px 8px; border-radius: 4px; font-weight: bold; }
        </style>
    </head>
    <body>
        <div class="container">
            <a href="/logout" class="logout">ထွက်မည် (Logout)</a>
            <h2>🏪 ဆိုင်အမည်: {{ session['shop_name'] }}</h2>
            <p>ကြိုဆိုပါတယ်, <strong>{{ session['username'] }}</strong></p>
            <hr>

            <!-- Daily Summary Cards -->
            <h3 style="margin-bottom: 5px; color: #333;">📊 ယနေ့ ဝင်ငွေ/ထွက်ငွေ စာရင်းချုပ် (Daily Summary)</h3>
            <div class="summary-cards">
                <div class="card in">
                    <h4>စုစုပေါင်း ငွေသွင်း (Cash In)</h4>
                    <div class="value" style="color: #28a745;">{{ "{:,.2f}".format(total_cash_in) }} Ks</div>
                </div>
                <div class="card out">
                    <h4>စုစုပေါင်း ငွေထုတ် (Cash Out)</h4>
                    <div class="value" style="color: #dc3545;">{{ "{:,.2f}".format(total_cash_out) }} Ks</div>
                </div>
                <div class="card commission">
                    <h4>ရရှိမည့် ကော်မရှင် (Commission)</h4>
                    <div class="value" style="color: #e0a800;">{{ "{:,.2f}".format(total_commission) }} Ks</div>
                </div>
            </div>
            
            <div class="upload-box">
                <h3 style="margin-top: 0; color: #007bff;">💸 ငွေသွင်း/ငွေထုတ် ပြေစာ တင်ရန်</h3>
                <form action="/upload" method="POST" enctype="multipart/form-data">
                    <div class="form-group">
                        <label>ပြုလုပ်မှု အမျိုးအစား:</label>
                        <select name="tx_type" required>
                            <option value="Cash In">ငွေသွင်း (Cash In)</option>
                            <option value="Cash Out">ငွေထုတ် (Cash Out)</option>
                        </select>
                    </div>
                    <div class="form-group">
                        <label>ဖောက်သည် ဖုန်းနံပါတ်:</label>
                        <input type="text" name="customer_phone" placeholder="ဥပမာ - 09912345678" required>
                    </div>
                    <div class="form-group">
                        <label>ကော်မရှင် ရာခိုင်နှုန်း (%):</label>
                        <input type="text" name="percentage" placeholder="ဥပမာ - 5 သို့မဟုတ် 5%" required>
                    </div>
                    <div class="form-group">
                        <label>KBZPay / WavePay ပြေစာပုံ (Screenshot):</label>
                        <input type="file" name="screenshot" accept="image/*" required>
                    </div>
                    <button type="submit">ပြေစာ စစ်ဆေးပြီး သိမ်းဆည်းမည်</button>
                </form>
            </div>

            <h3 style="margin-top: 30px;">📋 ဤဆိုင်၏ ငွေလွှဲမှတ်တမ်းများနှင့် ကော်မရှင်စာရင်းများ</h3>
            <table>
                <thead>
                    <tr>
                        <th>စဉ်</th>
                        <th>အမျိုးအစား</th>
                        <th>ဖောက်သည်ဖုန်း</th>
                        <th>Transaction ID</th>
                        <th>ငွေပမာဏ</th>
                        <th>ဝန်ဆောင်ခ / ကော်မရှင်</th>
                        <th>အချိန်</th>
                    </tr>
                </thead>
                <tbody>
                    {% if transactions %}
                        {% for tx in transactions %}
                        <tr>
                            <td>{{ loop.index }}</td>
                            <td>
                                {% if tx['tx_type'] == 'Cash In' %}
                                    <span class="badge-in">Cash In</span>
                                {% else %}
                                    <span class="badge-out">Cash Out</span>
                                {% endif %}
                            </td>
                            <td>{{ tx['customer_phone'] }}</td>
                            <td style="font-family: monospace;">{{ tx['transaction_id'] }}</td>
                            <td style="color: #d9534f; font-weight: bold;">{{ tx['amount_str'] }}</td>
                            <td style="color: #007bff; font-weight: bold;">{{ tx['fee'] }}</td>
                            <td>{{ tx['date_time'] }}</td>
                        </tr>
                        {% endfor %}
                    {% else %}
                        <tr>
                            <td colspan="7" style="text-align: center; color: #777;">ယခုထိ ငွေလွှဲမှတ်တမ်း မရှိသေးပါ။</td>
                        </tr>
                    {% endif %}
                </tbody>
            </table>
        </div>
    </body>
    </html>
    ''', transactions=transactions, total_cash_in=total_cash_in, total_cash_out=total_cash_out, total_commission=total_commission)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = generate_password_hash(request.form['password'])
        shop_name = request.form['shop_name']
        try:
            conn = sqlite3.connect('pos_database.db')
            cursor = conn.cursor()
            cursor.execute('INSERT INTO users (username, password, shop_name) VALUES (?, ?, ?)', (username, password, shop_name))
            conn.commit()
            conn.close()
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            return "ဤ အကောင့်အမည် ရှိနှင့်ပြီးသား ဖြစ်ပါသည်။"
    return render_template_string('''
    <!DOCTYPE html>
    <html lang="my">
    <head><meta charset="UTF-8"><title>Register</title></head>
    <body style="font-family:sans-serif; background:#f4f7f6; display:flex; justify-content:center; align-items:center; height:100vh;">
        <div style="background:white; padding:30px; border-radius:8px; width:350px; box-shadow:0 2px 10px rgba(0,0,0,0.1);">
            <h2>ဆိုင်အကောင့်သစ် ဖွင့်ရန်</h2>
            <form method="POST">
                <input type="text" name="shop_name" placeholder="ဆိုင်အမည်" required style="width:100%; padding:10px; margin:10px 0; box-sizing:border-box;"><br>
                <input type="text" name="username" placeholder="Username" required style="width:100%; padding:10px; margin:10px 0; box-sizing:border-box;"><br>
                <input type="password" name="password" placeholder="Password" required style="width:100%; padding:10px; margin:10px 0; box-sizing:border-box;"><br>
                <button type="submit" style="width:100%; background:#007bff; color:white; padding:10px; border:none; border-radius:4px; cursor:pointer;">အကောင့်ဖွင့်မည်</button>
            </form>
            <a href="/login" style="display:block; text-align:center; margin-top:15px; color:#007bff; text-decoration:none;">ဝင်ရန်</a>
        </div>
    </body>
    </html>
    ''')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        conn = sqlite3.connect('pos_database.db')
        cursor = conn.cursor()
        cursor.execute('SELECT id, password, shop_name FROM users WHERE username = ?', (username,))
        user = cursor.fetchone()
        conn.close()
        if user and check_password_hash(user[1], password):
            session['user_id'] = user[0]
            session['username'] = username
            session['shop_name'] = user[2]
            return redirect(url_for('index'))
        else:
            return "အသုံးပြုသူအမည် သို့မဟုတ် စကားဝှက် မှားယွင်းနေပါသည်။ <a href='/login'>ပြန်ကြိုးစားရန်</a>"
    return render_template_string('''
    <!DOCTYPE html>
    <html lang="my">
    <head><meta charset="UTF-8"><title>Login</title></head>
    <body style="font-family:sans-serif; background:#f4f7f6; display:flex; justify-content:center; align-items:center; height:100vh;">
        <div style="background:white; padding:30px; border-radius:8px; width:350px; box-shadow:0 2px 10px rgba(0,0,0,0.1);">
            <h2>ဆိုင်အကောင့် ဝင်ရန်</h2>
            <form method="POST">
                <input type="text" name="username" placeholder="Username" required style="width:100%; padding:10px; margin:10px 0; box-sizing:border-box;"><br>
                <input type="password" name="password" placeholder="Password" required style="width:100%; padding:10px; margin:10px 0; box-sizing:border-box;"><br>
                <button type="submit" style="width:100%; background:#28a745; color:white; padding:10px; border:none; border-radius:4px; cursor:pointer;">ဝင်မည်</button>
            </form>
            <a href="/register" style="display:block; text-align:center; margin-top:15px; color:#007bff; text-decoration:none;">အကောင့်အသစ် ဖွင့်ရန်</a>
        </div>
    </body>
    </html>
    ''')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    tx_type = request.form.get('tx_type')
    customer_phone = request.form.get('customer_phone')
    percentage_str = request.form.get('percentage')
    
    if 'screenshot' not in request.files:
        return "File မပါဝင်ပါ"
    file = request.files['screenshot']
    if file.filename == '':
        return "ဖိုင်နာမည် မရှိပါ"
    if file:
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
        file.save(filepath)
        
        try:
            img = Image.open(filepath)
            extracted_text = pytesseract.image_to_string(img, lang='eng+mya')
            
            tx_id_match = re.search(r'\b\d{16,}\b', extracted_text)
            transaction_id = tx_id_match.group(0) if tx_id_match else None

            amount_match = re.search(r'([\d,]+\.\d{2}\s*Ks)', extracted_text)
            amount_str = amount_match.group(0) if amount_match else "0.00 Ks"

            if not transaction_id:
                return "Transaction ID ရှာမတွေ့ပါ။ <a href='/'>နောက်သို့</a>"

            clean_amount = amount_match.group(1).replace(',', '').replace('Ks', '').strip() if amount_match else "0"
            try:
                numeric_amount = float(clean_amount)
            except ValueError:
                numeric_amount = 0.0

            clean_percentage = percentage_str.replace('%', '').strip()
            try:
                percentage = float(clean_percentage)
            except ValueError:
                percentage = 0.0

            calculated_fee_value = numeric_amount * (percentage / 100.0)
            fee_str = f"{calculated_fee_value:,.2f} Ks (နှုန်း: {percentage}%)"

            current_shop_id = session['user_id']
            conn = sqlite3.connect('pos_database.db')
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM transactions WHERE shop_id = ? AND transaction_id = ?', (current_shop_id, transaction_id))
            existing_tx = cursor.fetchone()

            if existing_tx:
                conn.close()
                return "ဤ Transaction ID မှာ စာရင်းရှိပြီးသား ဖြစ်ပါသည်။ <a href='/'>နောက်သို့</a>"

            cursor.execute('''
                INSERT INTO transactions (shop_id, tx_type, customer_phone, transaction_id, amount, amount_str, fee_value, fee) 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (current_shop_id, tx_type, customer_phone, transaction_id, numeric_amount, amount_str, calculated_fee_value, fee_str))
            conn.commit()
            conn.close()

            return f"""
            <div style='font-family: sans-serif; padding: 20px; max-width: 600px; margin: auto;'>
                <h3 style='color: #28a745;'>✓ သိမ်းဆည်းပြီးပါပြီ</h3>
                <p><strong>ကော်မရှင် (Fee):</strong> {fee_str}</p>
                <br><a href='/' style='background:#007bff; color:white; padding:10px 15px; text-decoration:none; border-radius:4px;'>ပင်မသို့</a>
            </div>
            """
        except Exception as e:
            return f"အမှားအယွင်း: {str(e)}"

if __name__ == '__main__':
    app.run(debug=True)
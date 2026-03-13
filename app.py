from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import pytz

app = Flask(__name__)
CORS(app)

# --- GOOGLE SHEETS API SETUP ---
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
# Make sure your JSON key file is renamed to 'credentials.json' in your folder
creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
client = gspread.authorize(creds)

SPREADSHEET_NAME = "PU_Transit_Database"
WORKSHEET_NAME = "Students"

def get_worksheet():
    if creds.access_token_expired:
        client.login()
    sheet = client.open(SPREADSHEET_NAME)
    return sheet.worksheet(WORKSHEET_NAME)

# ==========================================
# 1. FRONTEND UI ROUTES (Restoring your pages)
# ==========================================

# Main Student Login Page
@app.route('/', methods=['GET'])
def home():
    return render_template('login.html')

# Student Dashboard
@app.route('/dashboard', methods=['GET'])
def student_dashboard():
    return render_template('dashboard.html')

# Driver Login
@app.route('/driver', methods=['GET'])
def driver_login():
    return render_template('driver_login.html')

# Driver Dashboard (YOUR QR SCANNER UI)
@app.route('/driver_dashboard', methods=['GET'])
def driver_dashboard():
    return render_template('driver_dashboard.html')

# Admin Routes
@app.route('/admin', methods=['GET'])
def admin_login():
    return render_template('admin_login.html')

@app.route('/admin_dashboard', methods=['GET'])
def admin_dashboard():
    return render_template('admin_dashboard.html')


# ==========================================
# 2. THE NEW QR SCANNER BACKEND LOGIC
# ==========================================
@app.route('/scan', methods=['POST'])
def process_scan():
    data = request.json
    
    # Extract data sent by the QR scanner in driver_dashboard.html
    student_id = str(data.get('student_id')) 
    bus_id = str(data.get('bus_id'))

    worksheet = get_worksheet()
    records = worksheet.get_all_records()
    
    student_record = None
    row_index = 2 
    
    for record in records:
        if str(record.get('ID', '')) == student_id:
            student_record = record
            break
        row_index += 1

    if not student_record:
        return jsonify({"status": "denied", "message": "Unregistered Student QR"}), 404

    assigned_bus = str(student_record.get('assigned_bus', ''))
    if bus_id not in assigned_bus: 
        return jsonify({"status": "denied", "message": f"Wrong Bus! Assigned to {assigned_bus}"}), 403

    ist_now = datetime.now(pytz.timezone('Asia/Kolkata'))
    today_str = ist_now.strftime('%Y-%m-%d')
    
    last_scan_date = str(student_record.get('last_scan_date', ''))
    
    try:
        daily_scan_count = int(student_record.get('daily_scan_count', 0))
    except ValueError:
        daily_scan_count = 0

    if last_scan_date != today_str:
        last_scan_date = today_str
        daily_scan_count = 0

    if daily_scan_count >= 2:
        return jsonify({
            "status": "denied", 
            "message": "Daily Limit Reached. QR Locked until tomorrow."
        }), 403

    daily_scan_count += 1
    student_name = student_record.get('Name', 'Student')

    date_col = worksheet.find('last_scan_date').col
    count_col = worksheet.find('daily_scan_count').col
    
    worksheet.update_cell(row_index, date_col, last_scan_date)
    worksheet.update_cell(row_index, count_col, daily_scan_count)

    return jsonify({
        "status": "success", 
        "message": f"Welcome {student_name}. Ride {daily_scan_count}/2 Approved."
    }), 200


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)

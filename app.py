from flask import Flask, render_template, request, redirect, url_for, session, flash
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import os
from datetime import datetime
import pytz
from itsdangerous import URLSafeTimedSerializer, SignatureExpired # NEW: For TOTP Security

app = Flask(__name__)
app.secret_key = "pu_transit_secure_key_2026_final" 
s = URLSafeTimedSerializer(app.secret_key) # Initializes the TOTP Generator

# --- DATABASE SETUP ---
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
client = gspread.authorize(creds)
sheet = client.open("PU_Transit_Database") 

def get_ist_time():
    ist = pytz.timezone('Asia/Kolkata')
    return datetime.now(ist).strftime('%Y-%m-%d %H:%M:%S')

@app.route('/', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        role = request.form.get('role') 
        user_id = request.form.get('user_id', '').strip()
        password = request.form.get('password', '').strip()
        
        target = "Students" if role == "Student" else "Staff"
        ws = sheet.worksheet(target)
        user = next((item for item in ws.get_all_records() if str(item.get("ID", "")).strip() == user_id), None)

        if user and str(user.get("Password", "")).strip() == password:
            session.update({'user_id': user_id, 'role': role})
            return redirect(url_for('dashboard'))
        else:
            error = "Invalid Credentials"
    return render_template('login.html', error=error)

@app.route('/driver/login', methods=['GET', 'POST'])
def driver_login():
    error = None
    if request.method == 'POST':
        user_id = request.form.get('user_id', '').strip()
        password = request.form.get('password', '').strip()
        
        driver_sheet = sheet.worksheet("Drivers")
        driver = next((item for item in driver_sheet.get_all_records() if str(item.get("ID", "")).strip() == user_id), None)
        
        if driver and str(driver.get("Password", "")).strip() == password:
            session.update({
                'user_id': user_id, 
                'role': 'Driver', 
                'driver_name': driver.get("Name"),
                'assigned_bus': str(driver.get("Assigned_Bus")) 
            })
            return redirect(url_for('driver_dashboard'))
        else:
            error = "Invalid Driver Credentials"
    return render_template('driver_login.html', error=error)

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    error = None
    if request.method == 'POST':
        user_id = request.form.get('user_id', '').strip()
        password = request.form.get('password', '').strip()
        
        admin_sheet = sheet.worksheet("Admins")
        admin_user = next((item for item in admin_sheet.get_all_records() if str(item.get("Name", "")).strip() == user_id), None)
        
        if admin_user and str(admin_user.get("Password", "")).strip() == password:
            session.update({'user_id': user_id, 'role': 'Admin'})
            return redirect(url_for('admin_dashboard'))
        else:
            error = "Invalid Admin Credentials"
    return render_template('admin_login.html', error=error)

# ==========================================
# ATTENDANCE LOGIC (TOTP + 4-STEP SCAN)
# ==========================================
@app.route('/mark_attendance', methods=['POST'])
def mark_attendance():
    encrypted_token = request.form.get('scanned_id')
    bus_number = request.form.get('bus_number') 
    
    # 1. Verify the TOTP Token
    try:
        # Max age is 300 seconds (5 minutes). If older, it fails.
        scanned_id = s.loads(encrypted_token, max_age=300)
    except SignatureExpired:
        flash("Error: QR Code Expired. Student must refresh their app.")
        return redirect(url_for('driver_dashboard'))
    except Exception:
        flash("Error: Invalid or Fake QR Code.")
        return redirect(url_for('driver_dashboard'))

    # 2. Find the User
    person, role = None, ""
    for s_name in ["Students", "Staff"]:
        ws = sheet.worksheet(s_name)
        person = next((item for item in ws.get_all_records() if str(item.get("ID")) == scanned_id), None)
        if person:
            role = "Student" if s_name == "Students" else "Staff"
            break
            
    if not person:
        flash("Error: User ID not found.")
        return redirect(url_for('driver_dashboard'))

    # 3. Determine the 4-Step Scan Type
    attendance_ws = sheet.worksheet("Attendance")
    all_logs = attendance_ws.get_all_records()
    today = get_ist_time().split(' ')[0]
    
    # Count how many times this specific user scanned TODAY
    user_scans_today = [log for log in all_logs if str(log.get('ID')) == str(scanned_id) and today in str(log.get('Timestamp'))]
    scan_count = len(user_scans_today)
    
    scan_sequence = ["Morning In", "Morning Out", "Afternoon In", "Afternoon Out"]
    
    if scan_count >= 4:
        current_scan_type = "Extra Scan" # If they scan a 5th time
    else:
        current_scan_type = scan_sequence[scan_count]

    # 4. Fetch Shift and Log it
    shift = person.get("Shift", "N/A")

    attendance_ws.append_row([
        scanned_id, person.get("Name"), bus_number, get_ist_time(),
        role, person.get("Boarding_Point", "N/A"), current_scan_type, shift
    ])
    
    flash(f"Success: {person.get('Name')} - {current_scan_type}")
    return redirect(url_for('driver_dashboard'))

@app.route('/driver_dashboard')
def driver_dashboard():
    if session.get('role') != 'Driver': return redirect(url_for('driver_login'))
    
    assigned_bus = session.get('assigned_bus')
    try:
        all_logs = sheet.worksheet("Attendance").get_all_records()
        today = get_ist_time().split(' ')[0]
        bus_logs = [r for r in all_logs if str(r.get('Bus_Number', '')) == str(assigned_bus) and today in str(r.get('Timestamp', ''))]
        bus_logs.reverse() 
    except Exception:
        bus_logs = []

    return render_template('driver_dashboard.html', logs=bus_logs)

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session: return redirect(url_for('login'))
    
    # Generate the encrypted expiring token
    token = s.dumps(session['user_id'])
    
    return render_template('dashboard.html', token=token)

@app.route('/admin_dashboard')
def admin_dashboard():
    if session.get('role') != 'Admin': return redirect(url_for('admin_login'))
    return render_template('admin_dashboard.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)

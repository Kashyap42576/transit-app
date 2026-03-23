from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import os
from datetime import datetime
import pytz
import requests
import base64
import time

app = Flask(__name__)
app.secret_key = "pu_transit_secure_key_2026_final" 

# --- DATABASE SETUP ---
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
client = gspread.authorize(creds)
sheet = client.open("PU_Transit_Database") 

def get_ist_time():
    ist = pytz.timezone('Asia/Kolkata')
    return datetime.now(ist).strftime('%Y-%m-%d %H:%M:%S')

# ==========================================
# LOGIN ROUTES
# ==========================================
@app.route('/', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        role = request.form.get('role') 
        user_id = request.form.get('user_id', '').strip()
        password = request.form.get('password', '').strip()

        target = "Students" if role == "Student" else "Staff"
        ws = sheet.worksheet(target)
        try:
            user = next((item for item in ws.get_all_records() if str(item.get("ID", "")).strip() == user_id), None)
        except Exception:
            user = None

        if user and str(user.get("Password", "")).strip() == password:
            session.update({'user_id': user_id, 'role': role, 'user_name': user.get("Name", "User")})
            
            if 'pending_bus' in session:
                bus = session.pop('pending_bus')
                return redirect(url_for('scan_bus', bus_id=bus))
                
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
        try:
            driver = next((item for item in driver_sheet.get_all_records() if str(item.get("ID", "")).strip() == user_id), None)
        except Exception:
            driver = None

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

# ==========================================
# UNIFIED DASHBOARD & PHOTO UPLOAD
# ==========================================
@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session or session.get('role') in ['Driver', 'Admin']: 
        return redirect(url_for('login'))
        
    target = "Students" if session['role'] == "Student" else "Staff"
    ws = sheet.worksheet(target)
    
    try:
        user = next((item for item in ws.get_all_records() if str(item.get("ID", "")).strip() == str(session['user_id'])), None)
    except Exception:
        user = None

    photo_url = user.get("Photo_URL", "") if user else ""
    # Passing no bus_id means it will render the standard profile view
    return render_template('dashboard.html', user_name=session.get('user_name'), photo_url=photo_url)

@app.route('/upload_photo', methods=['POST'])
def upload_photo():
    if 'user_id' not in session: return redirect(url_for('login'))

    file = request.files.get('photo')
    if not file:
        flash("No file selected.")
        return redirect(url_for('dashboard'))

    IMGBB_API_KEY = "4882000cc942a1f5d38c1b5636d84a35" 

    try:
        payload = {
            "key": IMGBB_API_KEY,
            "image": base64.b64encode(file.read()).decode('utf-8')
        }
        res = requests.post("https://api.imgbb.com/1/upload", data=payload)
        upload_data = res.json()

        if "data" in upload_data:
            permanent_url = upload_data["data"]["url"]
            target = "Students" if session['role'] == "Student" else "Staff"
            ws = sheet.worksheet(target)

            cell = ws.find(str(session['user_id']))
            headers = ws.row_values(1)

            if "Photo_URL" not in headers:
                col_index = len(headers) + 1
                ws.update_cell(1, col_index, "Photo_URL")
            else:
                col_index = headers.index("Photo_URL") + 1

            ws.update_cell(cell.row, col_index, permanent_url)
            
            # If they were trying to board before uploading, auto-redirect them to the bus now
            if 'pending_bus' in session:
                bus = session.pop('pending_bus')
                flash("📸 Photo uploaded successfully! You are ready to board.")
                return redirect(url_for('scan_bus', bus_id=bus))
            
            flash("📸 Photo uploaded successfully! You can now board the buses.")
        else:
            flash("Error uploading photo to cloud. Please try again.")

    except Exception as e:
        flash(f"Upload failed: {str(e)}")

    return redirect(url_for('dashboard'))

# ==========================================
# STUDENT SCANS THE BUS QR CODE
# ==========================================
@app.route('/b/<bus_id>')
def scan_bus(bus_id):
    formatted_bus_id = bus_id.replace("_", " ")

    if 'user_id' not in session:
        session['pending_bus'] = bus_id
        flash("Please log in to board the bus.")
        return redirect(url_for('login'))

    if session.get('role') in ['Driver', 'Admin']:
        return "Drivers/Admins cannot board as passengers."
        
    target = "Students" if session['role'] == "Student" else "Staff"
    ws = sheet.worksheet(target)
    try:
        user = next((item for item in ws.get_all_records() if str(item.get("ID", "")).strip() == str(session['user_id'])), None)
        photo_url = user.get("Photo_URL", "") if user else ""
        if not photo_url or photo_url == "N/A":
            session['pending_bus'] = bus_id
            flash("You must upload a profile photo before boarding.")
            return redirect(url_for('dashboard'))
    except Exception:
        pass

    # Render the unified dashboard, passing the bus_id to trigger the Boarding UI
    return render_template('dashboard.html', bus_id=formatted_bus_id, user_name=session.get('user_name'))

@app.route('/api/confirm_boarding', methods=['POST'])
def confirm_boarding():
    if 'user_id' not in session:
        return jsonify({"status": "error", "message": "Not logged in", "audio": "Authentication failed."})

    data = request.json
    bus_number = data.get('bus_id') 
    student_id = session['user_id']

    target_ws_name = "Students" if session.get('role') == "Student" else "Staff"
    ws = sheet.worksheet(target_ws_name)
    
    try:
        person = next((item for item in ws.get_all_records() if str(item.get("ID", "")).strip() == str(student_id)), None)
    except Exception:
        person = None

    if not person:
        return jsonify({"status": "error", "message": "User ID not found in Database.", "audio": "User not found."})

    allowed_buses = str(person.get("Assigned_Bus", person.get("assigned bus", person.get("assigned_bus", ""))))
    if bus_number not in allowed_buses:
        return jsonify({"status": "error", "message": f"Assigned to {allowed_buses}, not {bus_number}.", "audio": "Access Denied. Wrong bus."})

    matched_full_bus = bus_number
    for b in allowed_buses.split(','):
        if bus_number in b:
            matched_full_bus = b.strip()
            break

    today = get_ist_time().split(' ')[0]
    last_scan_date = str(person.get('last_scan_date', person.get('Last_Scan_Date', '')))
    
    try:
        daily_scan_count = int(person.get('daily_scan_count', person.get('Daily_Scan_Count', 0)))
    except ValueError:
        daily_scan_count = 0

    if last_scan_date != today:
        last_scan_date = today
        daily_scan_count = 0

    if daily_scan_count >= 2:
        return jsonify({"status": "error", "message": "Daily limit of 2 rides reached.", "audio": "Access Denied. Daily limit reached."})

    daily_scan_count += 1
    current_scan_type = f"Ride {daily_scan_count} of 2"

    try:
        attendance_ws = sheet.worksheet("Attendance")
        shift = person.get("Shift", "N/A")
        boarding_pt = person.get("Boarding_Point", "N/A")
        photo_url = person.get("Photo_URL", "N/A")

        attendance_ws.append_row([
            student_id, person.get("Name"), matched_full_bus, get_ist_time(),
            session.get('role'), boarding_pt, current_scan_type, shift, photo_url
        ])

        cell = ws.find(str(student_id))
        headers = ws.row_values(1)

        date_col = headers.index("last_scan_date") + 1 if "last_scan_date" in headers else len(headers) + 1
        count_col = headers.index("daily_scan_count") + 1 if "daily_scan_count" in headers else len(headers) + 1

        if "last_scan_date" not in headers: ws.update_cell(1, date_col, "last_scan_date")
        if "daily_scan_count" not in headers: ws.update_cell(1, count_col, "daily_scan_count")

        ws.update_cell(cell.row, date_col, last_scan_date)
        ws.update_cell(cell.row, count_col, daily_scan_count)

        return jsonify({
            "status": "success", 
            "message": f"Approved: {current_scan_type}", 
            "audio": "Ride Approved. Welcome aboard."
        })

    except Exception as e:
        return jsonify({"status": "error", "message": "Database busy. Try again.", "audio": "Network error. Please try again."})

# ==========================================
# DRIVER & ADMIN DASHBOARDS
# ==========================================
@app.route('/driver_dashboard')
def driver_dashboard():
    if session.get('role') != 'Driver': return redirect(url_for('driver_login'))

    assigned_bus = session.get('assigned_bus')
    assigned_base = str(assigned_bus).split('-')[0].strip()

    try:
        all_logs = sheet.worksheet("Attendance").get_all_records()
        today = get_ist_time().split(' ')[0]
        
        bus_logs = []
        for r in all_logs:
            record_base = str(r.get('Bus_Number', '')).split('-')[0].strip()
            if record_base == assigned_base and today in str(r.get('Timestamp', '')):
                bus_logs.append(r)
                
        bus_logs.reverse() 
    except Exception:
        bus_logs = []

    return render_template('driver_dashboard.html', logs=bus_logs)

@app.route('/admin_dashboard')
def admin_dashboard():
    if session.get('role') != 'Admin': return redirect(url_for('admin_login'))

    try:
        attendance_ws = sheet.worksheet("Attendance")
        logs = attendance_ws.get_all_records()
        logs.reverse()  
        
        unique_buses = sorted(list(set(str(log.get('Bus_Number', '')) for log in logs if log.get('Bus_Number'))))
        unique_scan_types = sorted(list(set(str(log.get('Scan_Type', '')) for log in logs if log.get('Scan_Type'))))
        
    except Exception:
        logs = []
        unique_buses = []
        unique_scan_types = []

    return render_template('admin_dashboard.html', logs=logs, unique_buses=unique_buses, unique_scan_types=unique_scan_types)


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)

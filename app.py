from flask import Flask, render_template, request, redirect, url_for, session, flash
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import os
from datetime import datetime
import pytz
from itsdangerous import URLSafeTimedSerializer, SignatureExpired
import requests 
import base64   
import time  

app = Flask(__name__)
app.secret_key = "pu_transit_secure_key_2026_final" 
s = URLSafeTimedSerializer(app.secret_key)

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

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    error = None
    if request.method == 'POST':
        user_id = request.form.get('user_id', '').strip()
        password = request.form.get('password', '').strip()
        
        admin_sheet = sheet.worksheet("Admins")
        try:
            admin_user = next((item for item in admin_sheet.get_all_records() if str(item.get("Name", "")).strip() == user_id), None)
        except Exception:
            admin_user = None
            
        if admin_user and str(admin_user.get("Password", "")).strip() == password:
            session.update({'user_id': user_id, 'role': 'Admin'})
            return redirect(url_for('admin_dashboard'))
        else:
            error = "Invalid Admin Credentials"
    return render_template('admin_login.html', error=error)

# ==========================================
# STUDENT DASHBOARD & PHOTO UPLOAD
# ==========================================
@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session: return redirect(url_for('login'))
    
    target = "Students" if session['role'] == "Student" else "Staff"
    user = None
    
    # Retry logic for high traffic
    for attempt in range(3):
        try:
            ws = sheet.worksheet(target)
            user = next((item for item in ws.get_all_records() if str(item.get("ID", "")).strip() == str(session['user_id'])), None)
            break 
        except Exception as e:
            if attempt < 2:
                time.sleep(1.5) 
            else:
                pass 

    photo_url = user.get("Photo_URL", "") if user else ""
    token = s.dumps(session['user_id'])
    
    return render_template('dashboard.html', token=token, photo_url=photo_url)

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
            flash("📸 Photo uploaded successfully! Your QR code is now unlocked.")
        else:
            flash("Error uploading photo to cloud. Please try again.")

    except Exception as e:
        flash(f"Upload failed: {str(e)}")

    return redirect(url_for('dashboard'))

# ==========================================
# ATTENDANCE LOGIC (WITH ANTI-CRASH)
# ==========================================
@app.route('/mark_attendance', methods=['POST'])
def mark_attendance():
    encrypted_token = request.form.get('scanned_id')
    bus_number = request.form.get('bus_number') 
    
    try:
        scanned_id = s.loads(encrypted_token, max_age=300)
    except SignatureExpired:
        flash("🔴 Error: QR Code Expired. Student must refresh their app.")
        return redirect(url_for('driver_dashboard'))
    except Exception:
        flash("🔴 Error: Invalid QR Code. Is the student using the updated app?")
        return redirect(url_for('driver_dashboard'))

    person, role = None, ""
    for s_name in ["Students", "Staff"]:
        try:
            ws = sheet.worksheet(s_name)
            try:
                records = ws.get_all_records()
            except IndexError:
                records = []
            person = next((item for item in records if str(item.get("ID", "")).strip() == str(scanned_id)), None)
            if person:
                role = "Student" if s_name == "Students" else "Staff"
                break
        except Exception:
            pass 
            
    if not person:
        flash("🔴 Error: User ID not found in Database.")
        return redirect(url_for('driver_dashboard'))

    allowed_buses = str(person.get("Assigned_Bus", person.get("assigned bus", person.get("assigned_bus", ""))))
    if bus_number not in allowed_buses:
        flash(f"🔴 Access Denied: {person.get('Name')} is NOT assigned to {bus_number}.")
        return redirect(url_for('driver_dashboard'))

    max_retries = 3
    for attempt in range(max_retries):
        try:
            attendance_ws = sheet.worksheet("Attendance")
            
            try:
                all_logs = attendance_ws.get_all_records()
            except IndexError:
                headers = ["ID", "Name", "Bus_Number", "Timestamp", "Role", "Boarding_Point", "Scan_Type", "Shift", "Photo_URL"]
                attendance_ws.insert_row(headers, 1)
                all_logs = []

            today = get_ist_time().split(' ')[0]
            user_scans_today = [log for log in all_logs if str(log.get('ID')) == str(scanned_id) and today in str(log.get('Timestamp'))]
            scan_count = len(user_scans_today)
            
            scan_sequence = ["Morning In", "Morning Out", "Afternoon In", "Afternoon Out"]
            current_scan_type = "Extra Scan" if scan_count >= 4 else scan_sequence[scan_count]

            shift = person.get("Shift", "N/A")
            photo_url = person.get("Photo_URL", "https://cdn.pixabay.com/photo/2015/10/05/22/37/blank-profile-picture-973460_1280.png")

            attendance_ws.append_row([
                scanned_id, person.get("Name"), bus_number, get_ist_time(),
                role, person.get("Boarding_Point", "N/A"), current_scan_type, shift, photo_url
            ])
            
            flash(f"🟢 Success: {person.get('Name')} - {current_scan_type}")
            break 
            
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(2)
                continue
            
            if attempt == max_retries - 1:
                flash("⚠️ Database busy! Too many students boarding. Please scan again in 5 seconds.")
        
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

# ==========================================
# ADMIN DASHBOARD 
# ==========================================
@app.route('/admin_dashboard')
def admin_dashboard():
    if session.get('role') != 'Admin': return redirect(url_for('admin_login'))
    
    try:
        attendance_ws = sheet.worksheet("Attendance")
        logs = attendance_ws.get_all_records()
        logs.reverse()  
        
        # Get unique buses for the dropdown filter
        unique_buses = sorted(list(set(str(log.get('Bus_Number', '')) for log in logs if log.get('Bus_Number'))))
    except Exception:
        logs = []
        unique_buses = []

    return render_template('admin_dashboard.html', logs=logs, unique_buses=unique_buses)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)

from flask import Flask, render_template, request, redirect, url_for, session, flash
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import os
from datetime import datetime
import pytz

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

@app.route('/')
def index():
    return render_template('login.html')

# FIXED: Handles both GET (page load) and POST (form submission)
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user_type = request.form.get('user_type') 
        user_id = request.form.get('user_id')
        password = request.form.get('password')
        app_device_id = request.form.get('device_id', '').strip() 

        # ADMIN/DRIVER LOGIN
        if user_type == 'Admin':
            admin_sheet = sheet.worksheet("Admins")
            admin_user = next((item for item in admin_sheet.get_all_records() if str(item.get("Name")) == user_id), None)
            if admin_user and str(admin_user.get("Password")) == password:
                session.update({'user_id': user_id, 'role': 'Admin'})
                return redirect(url_for('admin_dashboard'))

        elif user_type == 'Driver':
            driver_sheet = sheet.worksheet("Drivers")
            driver = next((item for item in driver_sheet.get_all_records() if str(item.get("ID")) == user_id), None)
            if driver and str(driver.get("Password")) == password:
                session.update({
                    'user_id': user_id, 'role': 'Driver', 
                    'driver_name': driver.get("Name"),
                    'assigned_buses': str(driver.get("Assigned_Buses", "")).split(';')
                })
                return redirect(url_for('driver_dashboard'))

        # STUDENT/STAFF HARD-LOCK
        elif user_type in ['Student', 'Staff']:
            if not app_device_id or len(app_device_id) < 5:
                flash("Security Alert: Use the official PU Transit App.")
                return redirect(url_for('index'))

            target = "Students" if user_type == "Student" else "Staff"
            ws = sheet.worksheet(target)
            user = next((item for item in ws.get_all_records() if str(item.get("ID")) == user_id), None)

            if user and str(user.get("Password")) == password:
                stored_id = str(user.get("Device_ID", "")).strip()
                if not stored_id or stored_id in ["None", ""]:
                    cell = ws.find(user_id)
                    ws.update_cell(cell.row, 7, app_device_id) 
                elif stored_id != app_device_id:
                    flash("Security Alert: Device Mismatch.")
                    return redirect(url_for('index'))

                session.update({'user_id': user_id, 'role': user_type})
                return redirect(url_for('dashboard'))

        flash("Invalid Credentials")
    return redirect(url_for('index'))

# UPDATED: Matches your original form-based scanning
@app.route('/mark_attendance', methods=['POST'])
def mark_attendance():
    if session.get('role') != 'Driver':
        return redirect(url_for('index'))
    
    scanned_id = request.form.get('scanned_id')
    bus_number = request.form.get('bus_number')
    
    person = None
    role = ""
    for s_name in ["Students", "Staff"]:
        ws = sheet.worksheet(s_name)
        person = next((item for item in ws.get_all_records() if str(item.get("ID")) == scanned_id), None)
        if person:
            role = "Student" if s_name == "Students" else "Staff"
            break
            
    if person:
        attendance_sheet = sheet.worksheet("Attendance")
        attendance_sheet.append_row([
            scanned_id, person.get("Name"), bus_number, get_ist_time(),
            role, person.get("Boarding_Point", "N/A"), "Boarding"
        ])
        flash(f"Success: {person.get('Name')} marked!")
    else:
        flash("Error: User ID not found.")
        
    return redirect(url_for('driver_dashboard'))

@app.route('/driver_dashboard')
def driver_dashboard():
    if session.get('role') != 'Driver': return redirect(url_for('index'))
    return render_template('driver_dashboard.html', buses=session.get('assigned_buses'))

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session: return redirect(url_for('index'))
    return render_template('dashboard.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)

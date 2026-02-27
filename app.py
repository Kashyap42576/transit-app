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

# ==========================================
# 1. STUDENT & STAFF PORTAL (Main Page)
# ==========================================
@app.route('/', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        role = request.form.get('role') # Reads from your dropdown
        user_id = request.form.get('user_id')
        password = request.form.get('password')
        app_device_id = request.form.get('device_id', '').strip() 

        if not app_device_id or len(app_device_id) < 5:
            error = "Security Alert: Browser logins disabled. Use the PU Transit App."
        else:
            target = "Students" if role == "Student" else "Staff"
            ws = sheet.worksheet(target)
            user = next((item for item in ws.get_all_records() if str(item.get("ID")) == user_id), None)

            if user and str(user.get("Password")) == password:
                stored_id = str(user.get("Device_ID", "")).strip()
                if not stored_id or stored_id in ["None", ""]:
                    cell = ws.find(user_id)
                    ws.update_cell(cell.row, 7, app_device_id) 
                    session.update({'user_id': user_id, 'role': role})
                    return redirect(url_for('dashboard'))
                elif stored_id != app_device_id:
                    error = "Security Alert: Device Mismatch."
                else:
                    session.update({'user_id': user_id, 'role': role})
                    return redirect(url_for('dashboard'))
            else:
                error = "Invalid Credentials"

    return render_template('login.html', error=error)

# ==========================================
# 2. DRIVER PORTAL
# ==========================================
@app.route('/driver/login', methods=['GET', 'POST'])
def driver_login():
    error = None
    if request.method == 'POST':
        user_id = request.form.get('user_id')
        password = request.form.get('password')
        
        driver_sheet = sheet.worksheet("Drivers")
        driver = next((item for item in driver_sheet.get_all_records() if str(item.get("ID")) == user_id), None)
        
        if driver and str(driver.get("Password")) == password:
            session.update({
                'user_id': user_id, 
                'role': 'Driver', 
                'driver_name': driver.get("Name"),
                'assigned_bus': str(driver.get("Assigned_Bus")) # Permanent Bus Lock
            })
            return redirect(url_for('driver_dashboard'))
        else:
            error = "Invalid Driver Credentials"
            
    return render_template('driver_login.html', error=error)

# ==========================================
# 3. ADMIN PORTAL
# ==========================================
@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    error = None
    if request.method == 'POST':
        user_id = request.form.get('user_id')
        password = request.form.get('password')
        
        admin_sheet = sheet.worksheet("Admins")
        admin_user = next((item for item in admin_sheet.get_all_records() if str(item.get("Name")) == user_id), None)
        
        if admin_user and str(admin_user.get("Password")) == password:
            session.update({'user_id': user_id, 'role': 'Admin'})
            return redirect(url_for('admin_dashboard'))
        else:
            error = "Invalid Admin Credentials"
            
    return render_template('admin_login.html', error=error)

# ==========================================
# 4. ATTENDANCE & DASHBOARDS
# ==========================================
@app.route('/mark_attendance', methods=['POST'])
def mark_attendance():
    if session.get('role') != 'Driver': return redirect(url_for('login'))
    
    scanned_id = request.form.get('scanned_id')
    bus_number = request.form.get('bus_number') 
    
    person, role = None, ""
    for s_name in ["Students", "Staff"]:
        ws = sheet.worksheet(s_name)
        person = next((item for item in ws.get_all_records() if str(item.get("ID")) == scanned_id), None)
        if person:
            role = "Student" if s_name == "Students" else "Staff"
            break
            
    if person:
        sheet.worksheet("Attendance").append_row([
            scanned_id, person.get("Name"), bus_number, get_ist_time(),
            role, person.get("Boarding_Point", "N/A"), "Boarding"
        ])
        flash(f"Success: {person.get('Name')} marked!")
    else:
        flash("Error: User ID not found.")
        
    return redirect(url_for('driver_dashboard'))

@app.route('/manifest/<bus_number>')
def manifest(bus_number):
    if session.get('role') != 'Driver': return redirect(url_for('login'))
    all_logs = sheet.worksheet("Attendance").get_all_records()
    today = get_ist_time().split(' ')[0]
    bus_logs = [r for r in all_logs if str(r.get('Bus_Number')) == str(bus_number) and today in str(r.get('Timestamp'))]
    bus_logs.reverse()
    return render_template('manifest.html', bus_number=bus_number, driver_name=session.get('driver_name'), logs=bus_logs)

@app.route('/driver_dashboard')
def driver_dashboard():
    if session.get('role') != 'Driver': return redirect(url_for('login'))
    return render_template('driver_dashboard.html')

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session: return redirect(url_for('login'))
    return render_template('dashboard.html')

@app.route('/admin_dashboard')
def admin_dashboard():
    if session.get('role') != 'Admin': return redirect(url_for('login'))
    return render_template('admin_dashboard.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)

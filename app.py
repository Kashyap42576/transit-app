from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import gspread
import io
import csv
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'super_secret_key'

# --- GOOGLE SHEETS SETUP ---
try:
    # This automatically finds the credentials.json file you put in Render's Secret Files!
    gc = gspread.service_account(filename='credentials.json')
    sh = gc.open('Transit Database')
    
    students_sheet = sh.worksheet("Students")
    staff_sheet = sh.worksheet("Staff")
    drivers_sheet = sh.worksheet("Drivers")
    attendance_sheet = sh.worksheet("Attendance")
except Exception as e:
    print(f"CRITICAL ERROR: Could not connect to Google Sheets. {e}")

def get_users_db(role):
    db = {}
    try:
        if role == 'Driver':
            records = drivers_sheet.get_all_records()
            for row in records:
                db[str(row['CONTACT NUMBER']).strip()] = {
                    'name': str(row['DRIVER NAME']).strip(),
                    'assigned_bus': str(row['BUS NUMBER']).strip()
                }
            return db

        # For Students and Staff
        sheet_to_use = students_sheet if role == 'Student' else staff_sheet
        id_col = 'ENROLLMENT NO' if role == 'Student' else 'STAFF ID'
        
        records = sheet_to_use.get_all_records()
        for row in records:
            db[str(row[id_col]).strip()] = {
                'password': str(row['PASSWORD']).strip(), 
                'name': str(row['NAME']).strip(),
                'boarding_point': str(row.get('BOARDING POINT', '')).strip(),
                'shift': str(row.get('SHIFT', '')).strip(),
                'assigned_bus': str(row.get('assigned_bus', 'Unassigned')).strip()
            }
        return db
    except Exception as e:
        print(f"Error reading DB: {e}")
        return {}

def get_today_scans(user_id):
    today_str = datetime.now().strftime("%Y-%m-%d")
    count = 0
    try:
        records = attendance_sheet.get_all_records()
        for row in records:
            if str(row['ID Number']) == str(user_id) and str(row['Timestamp']).startswith(today_str):
                count += 1
    except: pass
    return count

def get_next_scan_type(count):
    scan_types = ['Morning IN', 'Morning OUT', 'Afternoon IN', 'Afternoon OUT']
    return scan_types[count] if count < 4 else "All Scans Completed"

@app.route('/')
def home():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        role = request.form['role']
        user_id = request.form.get('user_id').strip()
        password = request.form['password'].strip()
        
        db = get_users_db(role)
        
        if user_id in db and str(db[user_id]['password']) == password:
            session['user_id'] = user_id
            session['user_name'] = db[user_id]['name']
            session['role'] = role
            session['assigned_bus'] = db[user_id]['assigned_bus']
            session['boarding_point'] = db[user_id]['boarding_point']
            session['shift'] = db[user_id]['shift'] 
            return redirect(url_for('dashboard'))
        else:
            return render_template('login.html', error="Invalid ID or Password")
    return render_template('login.html')

@app.route('/driver/login', methods=['GET', 'POST'])
def driver_login():
    if request.method == 'POST':
        driver_name = request.form['driver_name'].strip()
        contact_number = request.form['contact_number'].strip()
        
        db = get_users_db('Driver')
        
        if contact_number in db and db[contact_number]['name'].lower() == driver_name.lower():
            session['user_id'] = contact_number
            session['user_name'] = db[contact_number]['name']
            session['role'] = 'Driver'
            session['assigned_bus'] = db[contact_number]['assigned_bus']
            return redirect(url_for('driver_dashboard'))
        else:
            return render_template('driver_login.html', error="Invalid Name or Contact Number")
    return render_template('driver_login.html')

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session or session.get('role') == 'Driver':
        return redirect(url_for('login'))
    
    display_buses = session.get('assigned_bus', '').replace(';', ' & ')
    today_count = get_today_scans(session['user_id'])
    
    return render_template('dashboard.html', 
                           name=session['user_name'],
                           role=session['role'],
                           assigned_bus=display_buses,
                           scans_completed=today_count,
                           next_scan=get_next_scan_type(today_count))

@app.route('/driver_dashboard')
def driver_dashboard():
    if 'user_id' not in session or session.get('role') != 'Driver':
        return redirect(url_for('driver_login'))
    
    assigned_bus = session['assigned_bus']
    today_str = datetime.now().strftime("%Y-%m-%d")
    passenger_logs = []
    
    try:
        records = attendance_sheet.get_all_records()
        for row in records:
            if str(row['Bus ID']) == assigned_bus and str(row['Timestamp']).startswith(today_str):
                passenger_logs.append(row)
        passenger_logs.reverse() 
    except: pass

    return render_template('driver_dashboard.html', 
                           driver_name=session['user_name'],
                           bus_number=assigned_bus,
                           logs=passenger_logs)

@app.route('/mark_attendance', methods=['POST'])
def mark_attendance():
    if 'user_id' not in session:
        return jsonify({'status': 'error', 'message': 'Not logged in'})

    data = request.get_json()
    bus_id_scanned = data.get('qr_content')
    
    today_count = get_today_scans(session['user_id'])
    if today_count >= 4:
        return jsonify({'status': 'error', 'message': 'Locked: You have completed all 4 scans today!'})
        
    scan_type = get_next_scan_type(today_count)
    assigned_bus_string = session.get('assigned_bus', '')
    
    if bus_id_scanned not in assigned_bus_string.split(';'):
        return jsonify({'status': 'error', 'message': f'Access Denied! Assigned to: {assigned_bus_string.replace(";", " or ")}.'})
    
    try:
        # PUSH DATA DIRECTLY TO GOOGLE SHEETS!
        attendance_sheet.append_row([
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"), 
            session['user_id'], 
            session['user_name'], 
            session['role'],
            session.get('boarding_point', 'N/A'), 
            session.get('shift', 'N/A'),          
            scan_type,
            bus_id_scanned
        ])
            
        return jsonify({
            'status': 'success', 
            'message': f'{scan_type} marked for {bus_id_scanned}!',
            'student_name': session['user_name'],
            'boarding_point': session.get('boarding_point', 'N/A'),
            'shift': session.get('shift', 'N/A')
        })
    except Exception as e:
        print(f"Error logging to sheet: {e}")
        return jsonify({'status': 'error', 'message': 'Server error.'})

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        if request.form['username'] == 'admin' and request.form['password'] == 'Transport_@admin':
            session['is_admin'] = True
            return redirect(url_for('admin_dashboard'))
        else: return render_template('admin_login.html', error="Invalid Credentials")
    return render_template('admin_login.html')

@app.route('/admin/dashboard', methods=['GET', 'POST'])
def admin_dashboard():
    if not session.get('is_admin'): return redirect(url_for('admin_login'))

    message = None
    if request.method == 'POST':
        if 'file' in request.files and 'route' in request.form and 'user_type' in request.form:
            file = request.files['file']
            route_assigned = request.form['route'] 
            user_type = request.form['user_type']
            
            if file and file.filename.endswith('.csv'):
                stream = io.StringIO(file.stream.read().decode("utf-8-sig"), newline=None)
                reader = csv.DictReader(stream)
                count = 0
                
                if user_type == 'Driver':
                    for row in reader:
                        drivers_sheet.append_row([
                            route_assigned, 
                            str(row['DRIVER NAME']).strip(), 
                            str(row['CONTACT NUMBER']).strip()
                        ])
                        count += 1
                else:
                    sheet_to_use = students_sheet if user_type == 'Student' else staff_sheet
                    id_col = 'ENROLLMENT NO' if user_type == 'Student' else 'STAFF ID'
                    
                    for row in reader:
                        # Append directly to the Google Sheet
                        sheet_to_use.append_row([
                            str(row['NAME']).strip(),
                            str(row[id_col]).strip(),
                            str(row['PASSWORD']).strip(),
                            str(row.get('BOARDING POINT', '')).strip(),
                            str(row.get('SHIFT', '')).strip(),
                            route_assigned
                        ])
                        count += 1
                            
                message = f'Sent {count} {user_type}(s) to Google Sheets for {route_assigned}!'

    # Pull live attendance for the admin dashboard view
    attendance_records = []
    try:
        attendance_records = attendance_sheet.get_all_records()
        attendance_records.reverse()
    except: pass

    return render_template('admin_dashboard.html', message=message, attendance=attendance_records)

@app.route('/admin/download')
def download_logs():
    # Now that it's in Google Sheets, we just redirect the Admin to the live Google Sheet URL!
    # Replace the ID below with your actual Google Sheet ID from the URL bar
    return redirect("https://docs.google.com/spreadsheets/") 

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)

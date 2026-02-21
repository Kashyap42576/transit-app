from flask import Flask, render_template, request, redirect, url_for, session, jsonify, send_file
import os
import csv
import io
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'super_secret_key'

STUDENT_DB_FILE = 'students.csv'
STAFF_DB_FILE = 'staff.csv'
DRIVER_DB_FILE = 'drivers.csv'
ATTENDANCE_FILE = 'attendance_log.csv'

if not os.path.exists(ATTENDANCE_FILE):
    with open(ATTENDANCE_FILE, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['Timestamp', 'ID Number', 'Name', 'Role', 'Boarding Point', 'Shift', 'Scan Type', 'Bus ID'])

def get_users_db(role):
    if role == 'Driver':
        db_file = DRIVER_DB_FILE
        if not os.path.exists(db_file): return {}
        db = {}
        try:
            with open(db_file, mode='r', encoding='utf-8-sig') as file:
                reader = csv.DictReader(file)
                for row in reader:
                    # Key is contact number for unique lookup
                    db[str(row['CONTACT NUMBER']).strip()] = {
                        'name': str(row['DRIVER NAME']).strip(),
                        'assigned_bus': str(row['BUS NUMBER']).strip()
                    }
            return db
        except: return {}

    db_file = STUDENT_DB_FILE if role == 'Student' else STAFF_DB_FILE
    id_col = 'ENROLLMENT NO' if role == 'Student' else 'STAFF ID'
    
    if not os.path.exists(db_file): return {}
    db = {}
    try:
        with open(db_file, mode='r', encoding='utf-8-sig') as file:
            reader = csv.DictReader(file)
            for row in reader:
                db[str(row[id_col]).strip()] = {
                    'password': str(row['PASSWORD']).strip(), 
                    'name': str(row['NAME']).strip(),
                    'boarding_point': str(row.get('BOARDING POINT', '')).strip(),
                    'shift': str(row.get('SHIFT', '')).strip(),
                    'assigned_bus': row.get('assigned_bus', 'Unassigned') 
                }
        return db
    except: return {}

def get_today_scans(user_id):
    if not os.path.exists(ATTENDANCE_FILE): return 0
    today_str = datetime.now().strftime("%Y-%m-%d")
    count = 0
    try:
        with open(ATTENDANCE_FILE, mode='r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row['ID Number'] == str(user_id) and row['Timestamp'].startswith(today_str):
                    count += 1
    except: pass
    return count

def get_next_scan_type(count):
    scan_types = ['Morning IN', 'Morning OUT', 'Afternoon IN', 'Afternoon OUT']
    return scan_types[count] if count < 4 else "All Scans Completed"

@app.route('/')
def home():
    return redirect(url_for('login'))

# --- MAIN STUDENT/STAFF LOGIN ---
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

# --- NEW: DEDICATED DRIVER LOGIN ---
@app.route('/driver/login', methods=['GET', 'POST'])
def driver_login():
    if request.method == 'POST':
        driver_name = request.form['driver_name'].strip()
        contact_number = request.form['contact_number'].strip()
        
        db = get_users_db('Driver')
        
        # Validates that the contact number exists AND the name matches
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
    
    if os.path.exists(ATTENDANCE_FILE):
        try:
            with open(ATTENDANCE_FILE, mode='r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row['Bus ID'] == assigned_bus and row['Timestamp'].startswith(today_str):
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
        with open(ATTENDANCE_FILE, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
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
    except:
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
                
                # --- DRIVER UPLOAD LOGIC ---
                if user_type == 'Driver':
                    db = get_users_db('Driver')
                    for row in reader:
                        contact = str(row['CONTACT NUMBER']).strip()
                        db[contact] = {
                            'name': str(row['DRIVER NAME']).strip(),
                            'assigned_bus': route_assigned
                        }
                        count += 1
                    with open(DRIVER_DB_FILE, 'w', newline='', encoding='utf-8') as f:
                        writer = csv.DictWriter(f, fieldnames=['BUS NUMBER', 'DRIVER NAME', 'CONTACT NUMBER'])
                        writer.writeheader()
                        for contact, d in db.items():
                            writer.writerow({'BUS NUMBER': d['assigned_bus'], 'DRIVER NAME': d['name'], 'CONTACT NUMBER': contact})
                
                # --- STUDENT/STAFF UPLOAD LOGIC ---
                else:
                    db = get_users_db(user_type)
                    id_col = 'ENROLLMENT NO' if user_type == 'Student' else 'STAFF ID'
                    db_file = STUDENT_DB_FILE if user_type == 'Student' else STAFF_DB_FILE
                    
                    for row in reader:
                        user_id = str(row[id_col]).strip()
                        if user_id in db:
                            current_routes = db[user_id]['assigned_bus'].split(';')
                            if route_assigned not in current_routes and len(current_routes) < 2:
                                db[user_id]['assigned_bus'] += ';' + route_assigned
                        else:
                            db[user_id] = {
                                'password': str(row['PASSWORD']).strip(),
                                'name': str(row['NAME']).strip(),
                                'boarding_point': str(row.get('BOARDING POINT', '')).strip(),
                                'shift': str(row.get('SHIFT', '')).strip(),
                                'assigned_bus': route_assigned 
                            }
                        count += 1
                    
                    with open(db_file, 'w', newline='', encoding='utf-8') as f:
                        writer = csv.DictWriter(f, fieldnames=['NAME', id_col, 'PASSWORD', 'BOARDING POINT', 'SHIFT', 'assigned_bus'])
                        writer.writeheader()
                        for uid, d in db.items():
                            writer.writerow({'NAME': d['name'], id_col: uid, 'PASSWORD': d['password'], 'BOARDING POINT': d['boarding_point'], 'SHIFT': d['shift'], 'assigned_bus': d['assigned_bus']})
                            
                message = f'Processed {count} {user_type}(s) for {route_assigned}!'

    attendance_records = []
    if os.path.exists(ATTENDANCE_FILE):
        try:
            with open(ATTENDANCE_FILE, mode='r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader: attendance_records.append(row)
            attendance_records.reverse()
        except: pass

    return render_template('admin_dashboard.html', message=message, attendance=attendance_records)

@app.route('/admin/download')
def download_logs():
    if not session.get('is_admin'): return redirect(url_for('admin_login'))
    if os.path.exists(ATTENDANCE_FILE): return send_file(ATTENDANCE_FILE, as_attachment=True)
    return "No logs found yet.", 404

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
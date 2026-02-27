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

# FIXED: Added ['GET', 'POST'] to prevent 405 errors
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user_type = request.form.get('user_type') 
        user_id = request.form.get('user_id')
        password = request.form.get('password')
        
        # Check Driver Login
        if user_type == 'Driver':
            driver_sheet = sheet.worksheet("Drivers")
            driver = next((item for item in driver_sheet.get_all_records() if str(item.get("ID")) == user_id), None)
            if driver and str(driver.get("Password")) == password:
                session.update({
                    'user_id': user_id, 
                    'role': 'Driver', 
                    'driver_name': driver.get("Name"),
                    'assigned_bus': str(driver.get("Assigned_Bus")) 
                })
                return redirect(url_for('driver_dashboard'))
        
        # (Add Student/Staff logic here similarly)
        
    return render_template('login.html')

@app.route('/driver_dashboard')
def driver_dashboard():
    if session.get('role') != 'Driver': return redirect(url_for('index'))
    return render_template('driver_dashboard.html')

# CRITICAL: Dynamic port binding for Render
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)

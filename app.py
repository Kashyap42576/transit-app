from flask import Flask, request, jsonify
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime
import pytz

app = Flask(__name__)

# --- GOOGLE SHEETS API SETUP ---
# Define the scope and authenticate using your Service Account JSON
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
client = gspread.authorize(creds)

# Open the specific Google Sheet and the "Students" tab
SPREADSHEET_NAME = "PU_Transit_Database"
WORKSHEET_NAME = "Students"

def get_worksheet():
    # Re-authorize if the token expired
    if creds.access_token_expired:
        client.login()
    sheet = client.open(SPREADSHEET_NAME)
    return sheet.worksheet(WORKSHEET_NAME)

# --- 1. ROOT HEALTH CHECK (Fixes the 404 Error) ---
@app.route('/', methods=['GET'])
def home():
    return "PU Transit API is Live and Running smoothly!", 200

# --- 2. THE MAIN SCANNER ENDPOINT ---
@app.route('/scan', methods=['POST'])
def process_scan():
    data = request.json
    
    # Extract data sent by the ESP32 scanner
    student_id = str(data.get('student_id')) 
    bus_id = str(data.get('bus_id'))

    worksheet = get_worksheet()
    
    # Fetch all data as a list of dictionaries
    records = worksheet.get_all_records()
    
    student_record = None
    row_index = 2 # Row 1 is headers, so data starts at row 2
    
    # Find the student by their ID
    for record in records:
        if str(record.get('ID', '')) == student_id:
            student_record = record
            break
        row_index += 1

    if not student_record:
        return jsonify({"status": "denied", "message": "Unregistered Student"}), 404

    # Verify Bus Assignment
    assigned_bus = str(student_record.get('assigned_bus', ''))
    if bus_id not in assigned_bus: 
        return jsonify({"status": "denied", "message": f"Wrong Bus! Assigned to {assigned_bus}"}), 403

    # Time & Date Logic (Indian Standard Time)
    ist_now = datetime.now(pytz.timezone('Asia/Kolkata'))
    today_str = ist_now.strftime('%Y-%m-%d')
    
    last_scan_date = str(student_record.get('last_scan_date', ''))
    
    # Handle empty counts gracefully
    try:
        daily_scan_count = int(student_record.get('daily_scan_count', 0))
    except ValueError:
        daily_scan_count = 0

    # If it's a new day, reset the count to 0
    if last_scan_date != today_str:
        last_scan_date = today_str
        daily_scan_count = 0

    # Enforce the 2-Scan Limit
    if daily_scan_count >= 2:
        return jsonify({
            "status": "denied", 
            "message": "Daily Limit Reached. Locked until tomorrow."
        }), 403

    # Approve and Increment
    daily_scan_count += 1
    student_name = student_record.get('Name', 'Student')

    # Update the Google Sheet Live
    date_col = worksheet.find('last_scan_date').col
    count_col = worksheet.find('daily_scan_count').col
    
    worksheet.update_cell(row_index, date_col, last_scan_date)
    worksheet.update_cell(row_index, count_col, daily_scan_count)

    return jsonify({
        "status": "success", 
        "message": f"Welcome {student_name}. Ride {daily_scan_count}/2 Approved."
    }), 200

if __name__ == '__main__':
    # Use host='0.0.0.0' so it can be accessed externally by Render and your ESP32
    app.run(host='0.0.0.0', port=5000)

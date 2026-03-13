from flask import Flask, request, jsonify
from datetime import datetime
import pytz # Used to ensure the server runs on Indian Standard Time (IST)

app = Flask(__name__)

# --- MOCK DATABASE ---
# In your real app, this will be replaced by your Google Sheets API (gspread) calls.
# Format: { "student_id": {"name": "Ayush", "assigned_bus": "GJ06 BX 8763", "last_scan_date": "2026-03-12", "daily_scan_count": 2} }
db = {
    "UID_12345": {
        "name": "Ayush",
        "assigned_bus": "GJ06 BX 8763",
        "last_scan_date": "2026-03-12", # Yesterday
        "daily_scan_count": 2
    }
}

@app.route('/scan', methods=['POST'])
def process_scan():
    data = request.json
    student_id = data.get('student_id')
    bus_id = data.get('bus_id')

    # 1. Check if student exists
    if student_id not in db:
        return jsonify({"status": "denied", "message": "Invalid QR / Unregistered Student"}), 404

    student = db[student_id]

    # 2. Check Bus Assignment (The "Wrong Bus" restriction)
    if student['assigned_bus'] != bus_id:
        return jsonify({"status": "denied", "message": f"Wrong Bus! Assigned to {student['assigned_bus']}"}), 403

    # 3. Time & Limit Logic
    ist_now = datetime.now(pytz.timezone('Asia/Kolkata'))
    today_str = ist_now.strftime('%Y-%m-%d')

    # Check if it's a new day to reset the counter
    if student['last_scan_date'] != today_str:
        student['last_scan_date'] = today_str
        student['daily_scan_count'] = 0  # Reset to zero!

    # 4. Enforce the 2-Scan Limit
    if student['daily_scan_count'] >= 2:
        return jsonify({
            "status": "denied", 
            "message": "Daily Limit Reached. Locked until tomorrow.",
            "rides_used": student['daily_scan_count']
        }), 403

    # 5. Approve and Increment
    student['daily_scan_count'] += 1
    
    # -> (Save the updated 'student' data back to your Google Sheet here) <-

    return jsonify({
        "status": "success", 
        "message": f"Welcome {student['name']}. Ride {student['daily_scan_count']} of 2 Approved.",
        "rides_used": student['daily_scan_count']
    }), 200

if __name__ == '__main__':
    app.run(debug=True, port=5000)

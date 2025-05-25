from flask import Flask, request
import threading
from main import run_outreach

app = Flask(__name__)

@app.route('/')
def home():
    return '✅ IG DM Automation is live.'

@app.route('/run', methods=['POST'])
def trigger_outreach():
    threading.Thread(target=run_outreach).start()
    return '✅ Outreach triggered', 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=3000)
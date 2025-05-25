import gspread
import os
from openai import OpenAI
from oauth2client.service_account import ServiceAccountCredentials

def run_outreach():
    # 1. Authenticate with Google Sheets
    scope = ['https://spreadsheets.google.com/feeds',
             'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_name('/etc/secrets/your-google-credentials.json', scope)
    client_sheet = gspread.authorize(creds)

    # 2. Open your sheet
    sheet = client_sheet.open("IG DM AUTOMATION").sheet1  # Name of your Google Sheet
    data = sheet.get_all_records()

    # 3. Set your OpenAI API key and client
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

    # 4. Fixed part of the DM offer
    core_message = "One of our fighters went 7-0 post-surgery after one tweak added 8% more power per strike. Want me to send over how?"

    # 5. Loop through rows, generate messages where missing
    for i, row in enumerate(data):
        if not row.get("Message"):
            name = row.get("Name", "fighter")
            notes = row.get("Notes", "").strip()

            prompt = (
                f"Write a casual Instagram DM to {name}. Include a short human opening based on this: '{notes}'. Then naturally transition into this offer: '{core_message}'. Make sure it flows well and sounds real."
            )

            response = client.chat.completions.create(
                model="gpt-4",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
                max_tokens=100
            )

            message = response.choices[0].message.content.strip()

            # Assumes Message is in column D (4th column)
            sheet.update_cell(i + 2, 4, message)

    print("All new messages generated.")

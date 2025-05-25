import openai
import gspread
import os
import json
from oauth2client.service_account import ServiceAccountCredentials

def run_outreach():
    creds_json = os.environ["GOOGLE_APPLICATION_CREDENTIALS"]
    with open("creds.json", "w") as f:
        f.write(creds_json)

    scope = ['https://spreadsheets.google.com/feeds',
             'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_name("creds.json", scope)
    client_sheet = gspread.authorize(creds)

    sheet = client_sheet.open("IG DM AUTOMATION").sheet1
    data = sheet.get_all_records()
    print(f"Rows pulled: {len(data)}")

    client = openai.OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    core_message = "One of our fighters went 7-0 post-surgery after one tweak added 8% more power per strike. Want me to send over how?"

    for i, row in enumerate(data):
        if not row.get("Message"):
            name = row.get("Name", "fighter")
            notes = row.get("Notes", "").strip()
            prompt = (
                f"Write a casual but calm Instagram DM to {name}. Use this note: '{notes}' as the human hook. Then naturally transition into this offer: '{core_message}'. Tone should match a smart, grounded performance coach."
            )
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
                max_tokens=100
            )
            message = response.choices[0].message.content.strip()
            print(f"Updating row {i + 2} with message: {message}")
            sheet.update_cell(i + 2, 4, message)

    print("All messages updated.")

# This must be OUTSIDE the function, not indented
run_outreach()

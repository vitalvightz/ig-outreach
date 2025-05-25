import openai
import gspread
import os
import json
from oauth2client.service_account import ServiceAccountCredentials

def run_outreach():
    # 1. Write the JSON credentials to a temp file
    creds_json = os.environ["GOOGLE_APPLICATION_CREDENTIALS"]
    with open("google-creds.json", "w") as f:
        f.write(creds_json)

    # 2. Authenticate with Google Sheets
    scope = ['https://spreadsheets.google.com/feeds',
             'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_name("google-creds.json", scope)
    client_sheet = gspread.authorize(creds)

    # 3. Open your sheet
    sheet = client_sheet.open("IG DM AUTOMATION").sheet1
    data = sheet.get_all_records()

    # 4. Set your OpenAI API key
    openai.api_key = os.environ["OPENAI_API_KEY"]

    # 5. Fixed part of the DM offer
    core_message = "One of our fighters went 7-0 post-surgery after one tweak added 8% more power per strike. Want me to send over how?"

    # 6. Loop through rows and generate messages
    for i, row in enumerate(data):
        if not row.get("Message"):
            name = row.get("Name", "fighter")
            notes = row.get("Notes", "").strip()

            prompt = (
                f"Write a calm, respectful Instagram DM to {name}. Start with a personalised note based on this: '{notes}'. Then transition into this offer: '{core_message}'. Make sure it flows naturally and keeps Unlxck's tone — confident, grounded, and professional. Avoid emojis or hashtags."
            )

            response = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.6,
                max_tokens=100
            )

            message = response.choices[0].message.content.strip()
            sheet.update_cell(i + 2, 4, message)

    print("Outreach complete.")

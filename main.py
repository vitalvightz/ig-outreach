import openai
import gspread
from oauth2client.service_account import ServiceAccountCredentials

def run_outreach():
    scope = ['https://spreadsheets.google.com/feeds',
             'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_name('your-google-credentials.json', scope)
    client = gspread.authorize(creds)

    sheet = client.open("IG DM AUTOMATION").sheet1
    data = sheet.get_all_records()

    openai.api_key = "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"

    core_message = "One of our fighters went 7-0 post-surgery after one tweak added 8% more power per strike. Want me to send over how?"

    for i, row in enumerate(data):
        if not row.get("Message"):
            name = row.get("Name", "fighter")
            notes = row.get("Notes", "").strip()
            personalised_line = notes if notes else "your recent fight performances"

            prompt = f"Write a casual Instagram DM to {name}. Mention {personalised_line}. Then smoothly bridge into this line: {core_message}. Tweak transitions if needed."

            response = openai.ChatCompletion.create(
                model="gpt-4",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
                max_tokens=100
            )

            message = response['choices'][0]['message']['content'].strip()
            sheet.update_cell(i + 2, 4, message)

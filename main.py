import openai
import gspread
import os
import json
from oauth2client.service_account import ServiceAccountCredentials

def run_outreach():
    # 1. Write Google credentials from secret to file
    creds_json = os.environ["GOOGLE_APPLICATION_CREDENTIALS"]
    with open("creds.json", "w") as f:
        f.write(creds_json)

    # 2. Authenticate with Google Sheets
    scope = ['https://spreadsheets.google.com/feeds',
             'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_name("creds.json", scope)
    client_sheet = gspread.authorize(creds)

    # 3. Open sheet and pull data
    sheet = client_sheet.open("IG DM AUTOMATION").sheet1
    data = sheet.get_all_records()
    print(f"Rows pulled: {len(data)}")

    # 4. Set OpenAI client
    client = openai.OpenAI(api_key=os.environ["OPENAI_API_KEY"])

    # 5. Core message
    core_message = "One of our fighters went 7-0 post-surgery after one tweak added 8% more power per strike. Want me to send over how?"

    # 6. Generate and write messages
    for i, row in enumerate(data):
        if not row.get("Message"):
            name = row.get("Name", "fighter")
            notes = row.get("Notes", "").strip()

            prompt = (
                f"You're a calm, sharp performance director writing an Instagram DM to {name}. Start with a short, natural line based on this: '{notes}', but do not say 'I heard'. Then, transition smoothly into this message: '{core_message}'. Keep it between 40–55 words. Tone must feel confident, grounded, and never salesy."
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

# Run the function
run_outreach()
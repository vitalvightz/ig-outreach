# outreach/run_outreach.py

import openai
import gspread
import os
import json
from oauth2client.service_account import ServiceAccountCredentials

def run_outreach():
    # Step 1: Write Google credentials from environment variable
    creds_json = os.environ["GOOGLE_APPLICATION_CREDENTIALS"]
    with open("creds.json", "w") as f:
        f.write(creds_json)

    # Step 2: Authenticate Google Sheets
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_name("creds.json", scope)
    client_sheet = gspread.authorize(creds)

    # Step 3: Fetch sheet data
    sheet = client_sheet.open("IG DM AUTOMATION").sheet1
    data = sheet.get_all_records()
    print(f"Rows pulled: {len(data)}")

    # Step 4: OpenAI client setup
    client = openai.OpenAI(api_key=os.environ["OPENAI_API_KEY"])

    # Step 5: Core guaranteed message
    core_message = "One of our fighters went 7-0 post-surgery after one tweak added 8% more power per strike. Want me to send over how?"

    for i, row in enumerate(data):
        if not row.get("Message"):
            name = row.get("Name", "fighter")
            notes = row.get("Notes", "").strip()

            prompt = (
                f"Write a calm, confident Instagram DM to {name}. Start with a short, natural line based on this note about them: '{notes}'. "
                f"Then flow into this message exactly as written: '{core_message}'. "
                f"Keep the tone grounded, non-salesy, and the message between 40–50 words."
            )

            # Step 6: Generate initial message
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
                max_tokens=150
            )
            message = response.choices[0].message.content.strip()

            # Step 7: Review the message
            review_prompt = f"""
You're reviewing an Instagram DM from a grounded performance director. 
Check if it:
- Flow is natural, precise and seamless
- Stays human, calm, not overhyped
- Uses the correct pronouns and tone
- Has no hallucinated facts
- Keeps it between 35-50 words

Return ONLY:
ACCEPTED
or
REWRITE: <fixed message>

Here’s the message:
\"\"\"{message}\"\"\"
"""
            review_response = client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": review_prompt}],
                temperature=0,
                max_tokens=200
            )
            review_text = review_response.choices[0].message.content.strip()

            # Step 8: Post-process result
            if review_text.startswith("REWRITE:"):
                final_message = review_text.replace("REWRITE:", "").strip()
            elif review_text == "ACCEPTED":
                final_message = message
            else:
                final_message = "REVIEW FAILED"

            # Step 9: Enforce core message if not present
            if "7-0 post-surgery" not in final_message:
                final_message = f"{final_message.rstrip('.')} — {core_message}"

            # Step 10: Save result
            if final_message != "REVIEW FAILED":
                sheet.update_cell(i + 2, 4, final_message)
                print(f"Updated row {i + 2}: {final_message}")
            else:
                print(f"Skipped row {i + 2}: Review failed")

    print("All messages processed.")

# Run it
run_outreach()
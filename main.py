No look at step 1. It didn’t have to be exact but not mentioning 7-0 streak is criminal: import openai
import gspread
import os
import json
from oauth2client.service_account import ServiceAccountCredentials

def run_outreach():
    # 1. Write Google credentials JSON from GitHub Actions secret
    creds_json = os.environ["GOOGLE_APPLICATION_CREDENTIALS"]
    with open("creds.json", "w") as f:
        f.write(creds_json)

    # 2. Authenticate with Google Sheets
    scope = ['https://spreadsheets.google.com/feeds',
             'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_name("creds.json", scope)
    client_sheet = gspread.authorize(creds)

    # 3. Open sheet and fetch records
    sheet = client_sheet.open("IG DM AUTOMATION").sheet1
    data = sheet.get_all_records()
    print(f"Rows pulled: {len(data)}")

    # 4. Set OpenAI client
    client = openai.OpenAI(api_key=os.environ["OPENAI_API_KEY"])

    # 5. Core message
    core_message = "One of our fighters went 7-0 post-surgery after one tweak added 8% more power per strike. Want me to send over how?"

    # 6. Generate and review messages
    for i, row in enumerate(data):
        if not row.get("Message"):
            name = row.get("Name", "fighter")
            notes = row.get("Notes", "").strip()

            prompt = (
                f"Write a calm, confident Instagram DM to {name}. Start with a short, natural line based on this note about them: '{notes}'. "
                f"Then flow into this message: '{core_message}', making sure it feels like a natural continuation — not forced or robotic. "
                f"Keep the tone grounded, non-salesy, and the message between 40–50 words."
            )

            # Initial message generation
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
                max_tokens=150
            )

            message = response.choices[0].message.content.strip()

            # Review the message
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

            if review_text.startswith("REWRITE:"):
                final_message = review_text.replace("REWRITE:", "").strip()
            elif review_text == "ACCEPTED":
                final_message = message
            else:
                final_message = "REVIEW FAILED"

            if final_message != "REVIEW FAILED":
                sheet.update_cell(i + 2, 4, final_message)
                print(f"Updated row {i + 2}: {final_message}")
            else:
                print(f"Skipped row {i + 2}: Review failed")

    print("All messages processed.")

# Run the script
run_outreach()
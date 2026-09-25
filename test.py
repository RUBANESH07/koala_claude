import requests
import json

URL = "http://18.189.220.6:5000/api/price"

payload = {
    "resort_name": "Marriott's Grand Chateau",
    "unit_name": "1 Bedroom Villa",
    "check_in": "12/21/2026",
    "check_out": "12/28/2026"
}

try:
    response = requests.post(URL, json=payload)

    print("Status Code:", response.status_code)
    print("\nResponse JSON:")
    print(json.dumps(response.json(), indent=2))

except requests.exceptions.ConnectionError:
    print("❌ Could not connect to API. Make sure Flask server is running.")
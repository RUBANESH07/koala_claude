import requests
import json

URL = "http://127.0.0.1:5000/api/price"

payload = {
    "resort_name": "Club Wyndham Bonnet Creek",
    "unit_name": "2 Bedroom Deluxe",
    "check_in": "12/21/2026",
    "check_out": "12/28/2026",
    # Sibling unit types at this resort with their known average listing price.
    # average_listing_price may be null (no data yet) or a number - both accepted.
    "unit_types": [
        {"id": 374, "name": "1 Bedroom Deluxe", "average_listing_price": 132.33},
        {"id": 380, "name": "1 Bedroom Deluxe", "average_listing_price": None},
        {"id": 3965, "name": "1 Bedroom Limit Suit (Kensington Woods, Oak Knoll, Sterling Forest, Stonecastle, Wellington Place, Stonecastle Place)", "average_listing_price": None},
        {"id": 377, "name": "1 Bedroom Presidential", "average_listing_price": None},
        {"id": 375, "name": "2 Bedroom Deluxe ", "average_listing_price": None},
        {"id": 378, "name": "2 Bedroom Presidential", "average_listing_price": None},
        {"id": 376, "name": "3 Bedroom Deluxe", "average_listing_price": 250},
        {"id": 379, "name": "3 Bedroom Presidential", "average_listing_price": None}
    ]
}

try:
    response = requests.post(URL, json=payload)

    print("Status Code:", response.status_code)
    print("\nResponse JSON:")
    print(json.dumps(response.json(), indent=2))

except requests.exceptions.ConnectionError:
    print("❌ Could not connect to API. Make sure Flask server is running.")
# """
# Pricing Wizard — entry point.

# Usage:
#     python main.py

# Prompts for resort name, unit name, check-in and check-out dates,
# then runs the full pricing pipeline and prints the result.
# """

# import sys
# from agents.orchestrator import run_cached


# def main() -> None:
#     print("=== Pricing Wizard ===\n")
#     try:
#         resort = input("Resort name:      ").strip()
#         unit   = input("Unit name:        ").strip()
#         checkin  = input("Check-in  (MM/DD/YYYY): ").strip()
#         checkout = input("Check-out (MM/DD/YYYY): ").strip()
#     except (KeyboardInterrupt, EOFError):
#         print("\nAborted.")
#         sys.exit(0)

#     print()
#     try:
#         result = run_cached(resort, unit, checkin, checkout)
#     except ValueError as exc:
#         print(f"Input error: {exc}")
#         sys.exit(1)

#     print(result)


# if __name__ == "__main__":
#     main()




from flask import Flask, request, jsonify
from agents.orchestrator import run_cached
from agents import cache
from dotenv import load_dotenv
import json
import sys

load_dotenv()

app = Flask(__name__)


@app.route("/api/price", methods=["POST"])
def price():
    try:
        data = request.get_json()

        print("Incoming payload:")
        print(json.dumps(data, indent=2))

        # Validate input
        resort = data.get("resort_name")
        unit = data.get("unit_name")
        checkin = data.get("check_in")
        checkout = data.get("check_out")
        # Optional: sibling unit types at this resort, e.g.
        # [{"id": 374, "name": "1 Bedroom Deluxe", "average_listing_price": 132.33}, ...]
        # average_listing_price may be null (no data yet) or a number — both accepted.
        unit_types = data.get("unit_types") or []

        if not all([resort, unit, checkin, checkout]):
            return jsonify({
                "success": False,
                "error": "Missing required fields"
            }), 400

        if not isinstance(unit_types, list):
            return jsonify({
                "success": False,
                "error": "unit_types must be a list"
            }), 400

        # Store the raw incoming payload in data/price_cache.json for this query
        cache.save_payload(resort, unit, checkin, checkout, data)

        # Call your existing logic
        result = run_cached(resort, unit, checkin, checkout, unit_types)

        return jsonify({
            "success": True,
            "data": result
        })

    except ValueError as exc:
        return jsonify({
            "success": False,
            "error": str(exc)
        }), 400

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route("/")
def home():
    return {"message": "Pricing Wizard API is running 🚀"}


if __name__ == "__main__":
    app.run(debug=True)
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
from dotenv import load_dotenv
import sys

load_dotenv()

app = Flask(__name__)


@app.route("/api/price", methods=["POST"])
def price():
    try:
        data = request.get_json()

        # Validate input
        resort = data.get("resort_name")
        unit = data.get("unit_name")
        checkin = data.get("check_in")
        checkout = data.get("check_out")

        if not all([resort, unit, checkin, checkout]):
            return jsonify({
                "success": False,
                "error": "Missing required fields"
            }), 400

        # Call your existing logic
        result = run_cached(resort, unit, checkin, checkout)

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
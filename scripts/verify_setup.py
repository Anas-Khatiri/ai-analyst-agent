"""Verification script to check Google ADK installation and Gemini API access."""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Load dotenv if available
from dotenv import load_dotenv


def verify_environment() -> bool:
    """Verify that the required environment variables are set and ADK library is present."""
    print("=== System Environment Verification ===")

    # Locate and load .env file
    project_root = Path(__file__).resolve().parents[1]
    env_file = project_root / ".env"
    if env_file.is_file():
        print(f"Loading environment variables from: {env_file}")
        load_dotenv(dotenv_path=env_file)
    else:
        print("Warning: No .env file found. Using current system environment.")

    # 1. Verify Google ADK Import
    try:
        import google.adk  # noqa: F401
        from google.adk.agents import Agent  # noqa: F401
        from google.adk.models import Gemini  # noqa: F401

        print("✅ Google ADK is installed successfully.")
    except ImportError as e:
        print(f"❌ Failed to import google-adk: {e}", file=sys.stderr)
        return False

    # 2. Verify Gemini API Key
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("❌ GEMINI_API_KEY environment variable is not set.", file=sys.stderr)
        return False
    elif api_key == "your_gemini_api_key_here":
        print("❌ GEMINI_API_KEY is still set to placeholder in .env.", file=sys.stderr)
        return False

    # Mask key for printing
    masked_key = api_key[:4] + "..." + api_key[-4:] if len(api_key) > 8 else "..."
    print(f"✅ GEMINI_API_KEY is present: {masked_key}")

    # 3. Test API connectivity with a simple check
    print("Attempting to connect to Gemini API...")
    try:
        from google.genai import Client

        # The Client resolves the API key from GEMINI_API_KEY automatically
        client = Client()
        # Test request using a fast model
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents="Say 'System ready' if you can read this.",
        )
        if response and response.text:
            print(f"✅ Gemini API communication succeeded. Response: '{response.text.strip()}'")
        else:
            print("❌ Gemini API returned an empty response.", file=sys.stderr)
            return False
    except Exception as e:
        print(f"❌ Gemini API communication failed: {e}", file=sys.stderr)
        return False

    print("=== All Verification Checks Passed ===")
    return True


if __name__ == "__main__":
    success = verify_environment()
    sys.exit(0 if success else 1)

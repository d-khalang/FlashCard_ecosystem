# main.py
import sys
import json
from app.db_core import get_conjugations

def main():
    if len(sys.argv) < 2:
        print("Usage: python main.py <italian_verb>")
        sys.exit(1)
    verb = sys.argv[1].strip()

    try:
        data = get_conjugations(verb)
        if not data:
            print(f"[ERROR] Verb '{verb}' not found in offline database")
            sys.exit(2)
    except Exception as e:
        print(f"[ERROR] {e}")
        sys.exit(3)

    print(json.dumps(data, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()

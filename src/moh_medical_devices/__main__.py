import argparse
import json
import logging

from .client import Client
from .pipeline import run_snapshot

parser = argparse.ArgumentParser(description="Read-only Medical Devices API snapshot")
parser.add_argument("--output", required=True)
parser.add_argument("--run-id", required=True)
parser.add_argument("--page-size", type=int, default=1000)
parser.add_argument("--max-pages", type=int)
parser.add_argument("--search", default="")
parser.add_argument("--declaration-only", action="store_true")
args = parser.parse_args()
logging.basicConfig(level=logging.INFO)
client = Client()
try:
    result = run_snapshot(client, args.output, args.run_id, page_size=args.page_size,
                          max_pages=args.max_pages, search=args.search,
                          declaration_only=args.declaration_only)
    print(json.dumps(result, ensure_ascii=False, indent=2))
finally:
    client.close()

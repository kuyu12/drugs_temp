import argparse
import json
import logging

from . import MedicalDevicesClient, MedicalDevicesConfig, fetch_medical_devices_dataframe

parser = argparse.ArgumentParser(description="Read-only Medical Devices API to pandas")
parser.add_argument("--page-size", type=int, default=1000)
parser.add_argument("--no-details", action="store_true")
parser.add_argument("--detail-workers", type=int, default=4)
parser.add_argument("--requests-per-second", type=float, default=2)
parser.add_argument("--search", default="")
parser.add_argument("--declaration-only", action="store_true")
args = parser.parse_args()
logging.basicConfig(level=logging.INFO)
client = MedicalDevicesClient(MedicalDevicesConfig())
try:
    devices_df = fetch_medical_devices_dataframe(
        client, page_size=args.page_size, include_details=not args.no_details,
        search=args.search, declaration_only=args.declaration_only,
        detail_workers=args.detail_workers, requests_per_second=args.requests_per_second,
    )
    print(json.dumps(devices_df.attrs["extraction"], ensure_ascii=False, indent=2))
    print(devices_df.head(20).to_string())
finally:
    client.close()

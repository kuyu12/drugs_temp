import argparse
from pathlib import Path

from app.config import get_settings
from app.pipeline import DrugRegistryPipeline
from app.services.drug_registry import DrugRegistryService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Weekly pipeline for checking health basket status against the Israeli Drug Registry."
    )
    parser.add_argument("--input", required=True, help="Path to the input CSV file")
    parser.add_argument("--output", required=True, help="Path to the output CSV file")
    parser.add_argument(
        "--input-column",
        default="drug_name",
        help="CSV column that contains the drug name",
    )
    parser.add_argument(
        "--skip-details",
        action="store_true",
        help="Skip the second lookup for detailed basket fields",
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="Ignore an existing output file and process all rows again",
    )
    parser.add_argument(
        "--max-variants",
        type=int,
        default=3,
        help="Maximum number of name variants to try per drug",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    settings = get_settings()
    service = DrugRegistryService(
        base_url=settings.drug_registry_base_url,
        timeout_seconds=settings.drug_registry_timeout_seconds,
        user_agent=settings.drug_registry_user_agent,
        min_request_delay_seconds=settings.min_request_delay_seconds,
        max_request_delay_seconds=settings.max_request_delay_seconds,
        retry_attempts=settings.retry_attempts,
        retry_backoff_seconds=settings.retry_backoff_seconds,
        block_cooldown_seconds=settings.block_cooldown_seconds,
        cache_dir=settings.cache_dir,
        cache_ttl_hours=settings.cache_ttl_hours,
    )
    pipeline = DrugRegistryPipeline(service, max_variants_per_drug=max(1, args.max_variants))
    results = pipeline.run(
        input_path=Path(args.input),
        output_path=Path(args.output),
        input_column=args.input_column,
        include_details=not args.skip_details,
        resume=not args.no_resume,
    )

    matched_count = sum(1 for result in results if result.resolution_status == "registry_match")
    not_found_count = sum(1 for result in results if result.resolution_status == "not_found_via_autocomplete")
    error_count = len(results) - matched_count - not_found_count
    print(f"Processed {len(results)} drugs")
    print(f"Matched rows: {matched_count}")
    print(f"Not found rows: {not_found_count}")
    print(f"Error rows: {error_count}")
    print(f"Output written to: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

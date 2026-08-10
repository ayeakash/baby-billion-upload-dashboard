"""
normalize_age_groups.py -- Normalize age groups to standard format (0-3, 3-6, 6+).
"""

import csv
import logging
from pathlib import Path
from config import AGE_GROUP_MAP, BATCHES_DIR

log = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
)


def normalize_age_group(age_group_str: str) -> str:
    """Normalize age group to standard format."""
    if not age_group_str:
        return ""

    # Handle multiple age groups (comma-separated)
    age_groups = [ag.strip() for ag in age_group_str.split(",")]
    normalized = []

    for ag in age_groups:
        ag_lower = ag.lower()
        # Try to find in mapping
        mapped = None
        for key, value in AGE_GROUP_MAP.items():
            if key in ag_lower:
                mapped = value
                break

        if mapped:
            if mapped not in normalized:
                normalized.append(mapped)
        else:
            # If not found in mapping, check if it's already a standard value
            if ag in ["0-3", "3-6", "6+"]:
                if ag not in normalized:
                    normalized.append(ag)
            else:
                log.warning(f"  Could not map age group: '{ag}'")

    return ", ".join(normalized) if normalized else age_group_str


def normalize_batch_csv(csv_file: Path) -> bool:
    """Normalize age groups in a batch CSV file."""
    try:
        # Read the CSV
        rows = []
        with open(csv_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            header = reader.fieldnames
            for row in reader:
                rows.append(row)

        # Normalize age groups
        changes = 0
        for row in rows:
            if 'age_groups' in row:
                original = row['age_groups']
                normalized = normalize_age_group(original)
                if original != normalized:
                    changes += 1
                    log.info(f"    '{original}' → '{normalized}'")
                    row['age_groups'] = normalized

        if changes == 0:
            log.info(f"  No changes needed")
            return True

        # Write back
        with open(csv_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=header)
            writer.writeheader()
            writer.writerows(rows)

        log.info(f"  Updated {changes} rows")
        return True

    except Exception as e:
        log.error(f"  Error: {e}")
        return False


def main():
    """Main entry point."""
    log.info("=" * 70)
    log.info("Normalize Age Groups in All Batch CSVs")
    log.info("=" * 70)

    batches_dir = Path(BATCHES_DIR) / "Stories_Batches"

    if not batches_dir.exists():
        log.error(f"Batches directory not found: {batches_dir}")
        return False

    csv_files = sorted(batches_dir.glob("Batch_*.csv"))

    if not csv_files:
        log.error("No batch CSV files found")
        return False

    log.info(f"\nFound {len(csv_files)} batch CSV files\n")

    for csv_file in csv_files:
        log.info(f"Processing: {csv_file.name}")
        if not normalize_batch_csv(csv_file):
            log.error(f"Failed to process {csv_file.name}")
            return False

    log.info("\n" + "=" * 70)
    log.info("Age groups normalized successfully!")
    log.info("=" * 70)
    return True


if __name__ == "__main__":
    main()

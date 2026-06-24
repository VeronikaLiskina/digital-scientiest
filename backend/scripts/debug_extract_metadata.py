import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[1]

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


from app.services.pdf_import import extract_publication_metadata_from_pdf


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python scripts/debug_extract_metadata.py path/to/file.pdf")
        return

    file_path = Path(sys.argv[1])

    metadata = extract_publication_metadata_from_pdf(
        file_path,
        original_name=file_path.name,
    )

    print("TITLE:", metadata.title)
    print("YEAR:", metadata.year)
    print("LANGUAGE:", metadata.language)
    print("DOI:", metadata.doi)

    print("\nAUTHORS:")
    for author in metadata.authors:
        print("-", author)

    print("\nKEYWORDS:")
    for keyword in metadata.keywords:
        print("-", keyword)

    print("\nTOPICS:")
    for topic in metadata.topics:
        print("-", topic)


if __name__ == "__main__":
    main()
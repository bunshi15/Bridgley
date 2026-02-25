import fnmatch
import os
import shutil
import zipfile
from pathlib import Path

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

OUTPUT_DIR = os.path.join(ROOT_DIR)
EXCLUSIONS = {"logs", "*.db", "*.cpython-312.pyc", "*.cpython-313.pyc"}
ARCHIVES = {
    "app": os.path.join(OUTPUT_DIR, "app"),
}

def should_exclude(path: Path):
    """
    Check EXCLUSIONS.
    :param path: Path.
    :return: True, if need to exclude.
    """
    for pattern in EXCLUSIONS:
        if fnmatch.fnmatch(path.name, pattern):
            return True
    for part in path.parts:
        for pattern in EXCLUSIONS:
            if fnmatch.fnmatch(part, pattern):
                return True
    return False

def create_clean_archive(source_dir, output_dir, archive_name):
    """
    Creates a zip archive from the source directory while excluding specific folders and files.
    :param source_dir: Path to the source directory.
    :param output_dir: Path to the temporary directory.
    :param archive_name: Name of the resulting archive.
    """
    temp_dir = output_dir / "temp_archive"
    archive_root_dir = temp_dir / archive_name  # The root folder in the archive

    # Step 1: Create a temporary directory
    if temp_dir.exists():
        try:
            shutil.rmtree(temp_dir)
        except PermissionError as e:
            print(f"Error removing temporary directory: {e}")
            raise
    temp_dir.mkdir(parents=True)
    archive_root_dir.mkdir(parents=True)

    # Step 2: Copy contents while excluding specified folders and files
    for root, dirs, files in os.walk(source_dir):
        rel_path = Path(root).relative_to(source_dir)
        dest_path = archive_root_dir / rel_path

        # Skip excluded directories
        dirs[:] = [d for d in dirs if not should_exclude(Path(root) / d)]

        # Create directories
        dest_path.mkdir(parents=True, exist_ok=True)

        # Copy files
        for file_name in files:
            file_path = Path(root) / file_name
            if not should_exclude(file_path):
                shutil.copy2(file_path, dest_path / file_name)

    # Step 3: Create the archive
    archive_path = output_dir / f"{archive_name}.zip"
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for root, dirs, files in os.walk(archive_root_dir):
            for file_name in files:
                file_path = Path(root) / file_name
                archive_path_inside = file_path.relative_to(temp_dir)  # Use temp_dir as base
                archive.write(file_path, arcname=archive_path_inside)

    # Step 4: Cleanup
    try:
        shutil.rmtree(temp_dir)
    except PermissionError as e:
        print(f"Error during cleanup: {e}")
        raise

    print(f"Archive created successfully: {archive_path}")


if __name__ == "__main__":
    if __name__ == "__main__":
        temp_dir = Path(OUTPUT_DIR)
        for archive_name, source_dir in ARCHIVES.items():
            create_clean_archive(source_dir, temp_dir, archive_name)



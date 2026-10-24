"""Environment and Configuration Verification Script.

Executes diagnostic checks on the Python runtime, virtual environment,
installed packages, directory hierarchy, and Pydantic configuration.
"""

import sys
from pathlib import Path

from pydantic import ValidationError

# Ensure project root is in sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


def check_python_version() -> bool:
    print(f"[*] Python Version: {sys.version.split()[0]}")
    if sys.version_info < (3, 12):  # noqa: UP036
        print("  [ERROR] Python version must be >= 3.12!")
        return False
    print("  [PASS] Python version requirement satisfied (>= 3.12)")
    return True


def check_virtual_environment() -> bool:
    in_venv = sys.prefix != sys.base_prefix
    print(f"[*] Virtual Environment Active: {in_venv}")
    print(f"    sys.prefix: {sys.prefix}")
    print(f"    sys.base_prefix: {sys.base_prefix}")
    if not in_venv:
        print("  [WARNING] You are running outside an active virtual environment!")
        return False
    print("  [PASS] Running inside isolated virtual environment")
    return True


def check_dependencies() -> bool:
    print("[*] Checking Core Dependencies...")
    required = [
        ("fastapi", "FastAPI application and routing"),
        ("httpx", "Configured provider HTTP client"),
        ("pydantic", "Pydantic data validation"),
        ("pydantic_settings", "Pydantic Settings for .env management"),
        ("pypdf", "PDF parsing"),
        ("qdrant_client", "Vector and semantic-cache storage"),
        ("sentence_transformers", "Local embeddings and tokenization"),
        ("pytest", "Pytest test runner"),
    ]
    all_ok = True
    for module_name, desc in required:
        try:
            mod = __import__(module_name)
            ver = getattr(mod, "__version__", "installed")
            print(f"  [PASS] {module_name} ({ver}) - {desc}")
        except ImportError as e:
            print(f"  [FAIL] {module_name} missing: {e}")
            all_ok = False
    return all_ok


def check_directories() -> bool:
    print("[*] Checking Project Directory Structure...")
    root = Path(__file__).resolve().parent.parent
    expected_dirs = [
        "backend/app/api",
        "backend/app/core",
        "backend/app/models",
        "backend/app/repositories",
        "backend/app/schemas",
        "backend/app/services",
        "dashboard",
        "data/documents",
        "evaluation/datasets",
        "evaluation/results",
        "scripts",
        "tests/unit",
        "tests/integration",
        "docs",
    ]
    all_ok = True
    for rel_dir in expected_dirs:
        dir_path = root / rel_dir
        if dir_path.is_dir():
            print(f"  [PASS] {rel_dir}/ exists")
        else:
            print(f"  [FAIL] {rel_dir}/ is missing")
            all_ok = False
    return all_ok


def check_configuration() -> bool:
    print("[*] Validating Application Settings via Pydantic...")
    try:
        from backend.app.core.config import Settings

        Settings(_env_file=None)
        print("  [PASS] Default settings validated without reading .env")
        return True
    except (ImportError, ValidationError, ValueError) as exc:
        print(f"  [FAIL] Configuration error ({type(exc).__name__})")
        return False


def main() -> int:
    print("=" * 60)
    print(" SEMANTIC CACHE RAG: PHASE 0 ENVIRONMENT VERIFICATION")
    print("=" * 60)

    checks = [
        ("Python Version", check_python_version),
        ("Virtual Environment", check_virtual_environment),
        ("Dependencies", check_dependencies),
        ("Directory Structure", check_directories),
        ("Pydantic Configuration", check_configuration),
    ]

    all_passed = True
    for _name, check_fn in checks:
        print("-" * 60)
        passed = check_fn()
        if not passed:
            all_passed = False

    print("=" * 60)
    if all_passed:
        print(" [ALL CHECKS PASSED] Environment is verified and ready for Phase 1!")
        print("=" * 60)
        return 0
    else:
        print(" [VERIFICATION FAILED] Please resolve the highlighted issues.")
        print("=" * 60)
        return 1


if __name__ == "__main__":
    sys.exit(main())

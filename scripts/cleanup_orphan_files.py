"""DB가 참조하지 않는 업로드 원본 파일을 찾아 정리한다.

    uv run python -m scripts.cleanup_orphan_files            # 목록만 출력 (dry-run)
    uv run python -m scripts.cleanup_orphan_files --delete   # 실제 삭제

주의: 업로드가 진행 중인 파일도 잠깐 동안은 고아처럼 보일 수 있으므로
트래픽이 없는 시간에 실행하거나 운영에서는 생성 후 일정 시간이 지난 파일만 대상으로 해야 한다.
"""

import argparse

from app.core.config import get_settings
from app.db.session import get_sessionmaker
from app.services.storage_maintenance import delete_orphans, find_orphan_keys
from app.storage.file_storage import LocalFileStorage


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--delete", action="store_true", help="실제로 삭제한다")
    args = parser.parse_args()

    storage = LocalFileStorage(get_settings().storage_dir)
    with get_sessionmaker()() as db:
        keys = delete_orphans(db, storage) if args.delete else find_orphan_keys(db, storage)
    action = "deleted" if args.delete else "found (dry-run)"
    print(f"{len(keys)} orphan file(s) {action}")
    for key in keys:
        print(f"  {key}")


if __name__ == "__main__":
    main()

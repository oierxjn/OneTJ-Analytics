from app.updater_repository import UpdateManifestRepository
from app.updater_schemas import UpdateCheckData, UpdateCheckQuery


class UpdateCheckService:
    def __init__(self, repository: UpdateManifestRepository) -> None:
        self.repository = repository

    def check(self, query: UpdateCheckQuery) -> UpdateCheckData:
        entry = self.repository.get(query.manifest_key)
        if entry is None:
            raise ValueError("unsupported platform or arch")

        has_update = self._has_update(
            current_version=query.current_version_tuple,
            current_build=query.current_build_number,
            latest_version=entry.latest_version_tuple,
            latest_build=entry.latest_build,
        )
        if not has_update:
            return UpdateCheckData(has_update=False)

        published_at = None
        if entry.published_at is not None:
            published_at = entry.published_at.isoformat().replace("+00:00", "Z")

        return UpdateCheckData(
            has_update=True,
            latest_version=entry.latest_version,
            latest_build=entry.latest_build,
            release_notes=entry.release_notes,
            published_at=published_at,
            mandatory=entry.mandatory,
            download_url=entry.download_url,
            sha256=entry.sha256,
            file_size=entry.file_size,
            min_supported_version=entry.min_supported_version,
        )

    @staticmethod
    def _has_update(
        # TODO: 版本元组需要类型规范
        current_version: tuple[int, ...],
        current_build: int,
        latest_version: tuple[int, ...],
        latest_build: int,
    ) -> bool:
        '''
        检查是否需要更新
        '''
        if latest_version > current_version:
            return True
        if latest_version < current_version:
            return False
        return latest_build > current_build

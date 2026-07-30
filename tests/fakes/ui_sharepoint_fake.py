"""Fake inyectable de UiSharePointReadPort (sin Graph real)."""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from app.application.ui.path_guard import UiAllowedRoots, assert_path_allowed
from app.application.ui.ports import (
    UiControlReadResult,
    UiDriveItemMeta,
    UiFileContent,
    UiManifestSummary,
)
from app.application.use_cases.payment_validation_process_control import (
    ProcessControlSnapshot,
)


@dataclass
class FakeUiSharePointRead:
    """Stub completo para pytest. Solo lectura en memoria."""

    roots: UiAllowedRoots
    controls: dict[str, UiControlReadResult] = field(default_factory=dict)
    metas: dict[str, UiDriveItemMeta] = field(default_factory=dict)
    files: dict[str, bytes] = field(default_factory=dict)
    manifests: dict[str, dict] = field(default_factory=dict)
    adelantados: UiDriveItemMeta | None = None
    download_calls: list[str] = field(default_factory=list)
    meta_calls: list[str] = field(default_factory=list)

    def _guard(self, path: str) -> str:
        return assert_path_allowed(path, roots=self.roots)

    async def read_process_control(self, bank_code: str) -> UiControlReadResult:
        if bank_code not in self.controls:
            raise KeyError(bank_code)
        snap_path = self.controls[bank_code].snapshot.control_file_path
        self._guard(snap_path)
        return self.controls[bank_code]

    async def get_item_meta(self, relative_path: str) -> UiDriveItemMeta:
        safe = self._guard(relative_path)
        self.meta_calls.append(safe)
        if safe in self.metas:
            return self.metas[safe]
        if safe in self.files or safe in self.manifests:
            return UiDriveItemMeta(
                path=safe,
                name=safe.rsplit("/", 1)[-1],
                web_url=f"https://sharepoint.example/{safe}?web=1",
                etag='"etag-1"',
                exists=True,
            )
        return UiDriveItemMeta(path=safe, exists=False)

    async def download_bytes(self, relative_path: str) -> UiFileContent:
        safe = self._guard(relative_path)
        self.download_calls.append(safe)
        if safe in self.manifests:
            raw = json.dumps(self.manifests[safe]).encode("utf-8")
            return UiFileContent(path=safe, content=raw, etag='"etag-1"')
        if safe not in self.files:
            raise FileNotFoundError(safe)
        return UiFileContent(path=safe, content=self.files[safe], etag='"etag-1"')

    async def get_web_url(self, relative_path: str) -> str | None:
        meta = await self.get_item_meta(relative_path)
        return meta.web_url if meta.exists else None

    async def read_merge_manifest_summary(self, relative_path: str) -> UiManifestSummary:
        safe = self._guard(relative_path)
        data = self.manifests.get(safe)
        if data is None:
            return UiManifestSummary(path=safe, exists=False)
        incomplete = data.get("incomplete_groups") or []
        outputs = data.get("outputs") or []
        return UiManifestSummary(
            path=safe,
            exists=True,
            etag='"etag-1"',
            status=str(data.get("manifest_status") or data.get("status") or ""),
            incomplete_group_count=len(incomplete) if isinstance(incomplete, list) else 0,
            complete_group_count=len(outputs) if isinstance(outputs, list) else 0,
            eligible_for_dry_run=data.get("eligible_for_dry_run")
            if isinstance(data.get("eligible_for_dry_run"), bool)
            else None,
            raw_keys=tuple(sorted(data.keys())),
        )

    async def adelantados_meta(self) -> UiDriveItemMeta | None:
        return self.adelantados


def make_fake_control(
    snap: ProcessControlSnapshot,
    *,
    web_url: str = "https://sharepoint.example/control?web=1",
    notify_job_id: str | None = None,
    merge_job_id: str | None = None,
    generate_job_id: str | None = None,
    finalize_job_id: str | None = None,
    apply_job_id: str | None = None,
) -> UiControlReadResult:
    return UiControlReadResult(
        snapshot=snap,
        meta=UiDriveItemMeta(
            path=snap.control_file_path,
            name=snap.control_file_path.rsplit("/", 1)[-1],
            web_url=web_url,
            etag='"ctrl-1"',
            exists=True,
        ),
        generate_job_id=generate_job_id,
        finalize_job_id=finalize_job_id,
        notify_job_id=notify_job_id,
        merge_job_id=merge_job_id,
        apply_job_id=apply_job_id,
    )

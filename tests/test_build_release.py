# -*- coding: utf-8 -*-
"""scripts/build_release.py 的单元测试（干跑推演核心逻辑）。

注：不用 pytest 的 tmp_path 夹具——DSH 沙盒下跨进程删除目录会被拒绝，
改为进程内 tempfile.mkdtemp 的替代方案（os.makedirs 自建自删，CI/Linux 同样正常）。
"""

import json
import shutil
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import build_release as br

_PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _tmp_dir(label: str) -> Path:
    """在工作区内建一个隔离临时目录（本进程自建，结束后可自删）。

    注：不用 tempfile.mkdtemp——DSH 沙盒曾对 mkdtemp 目录拒写；
    改用 os.makedirs（固定前缀 + uuid 后缀），并配合同进程 shutil.rmtree 清理。
    """
    path = _PROJECT_ROOT / f"onetj_ut_{label}_{uuid.uuid4().hex[:8]}"
    path.mkdir(parents=False, exist_ok=False)
    return path


def _cleanup(p: Path) -> None:
    """尽力清理临时目录；沙盒残留可忽略（名字带 onetj_ut_ 前缀便于识别）。"""
    try:
        shutil.rmtree(p, ignore_errors=True)
    except Exception:
        pass


def _release_cfg(root: Path, **overrides) -> br.ReleaseConfig:
    """构造默认 ReleaseConfig，可用 overrides 覆盖字段。"""
    defaults = dict(
        collect_dir=root / "collect",
        download_base="https://example.com/downloads",
        iscc_override=None,
        release_notes_file=root / "notes.md",
        mandatory=False,
        min_supported_version="2.0.0",
        output_manifest=root / "manifest.json",
    )
    defaults.update(overrides)
    return br.ReleaseConfig(**defaults)


# ---------------------------------------------------------------------------
# 版本解析
# ---------------------------------------------------------------------------

def test_parse_pubspec_version_with_build():
    v = br.parse_pubspec_version("version: 2.5.0+18\n")
    assert v.version_name == "2.5.0"
    assert v.build_number == "18"


def test_parse_pubspec_version_without_build():
    v = br.parse_pubspec_version("version: 2.5.0")
    assert v.version_name == "2.5.0"
    assert v.build_number == ""


def test_parse_pubspec_version_invalid():
    with pytest.raises(ValueError):
        br.parse_pubspec_version("version: abc\n")
    with pytest.raises(ValueError):
        br.parse_pubspec_version("name: onetj\n")  # 没有 version 行


# ---------------------------------------------------------------------------
# 产物命名
# ---------------------------------------------------------------------------

def test_windows_installer_name():
    v = br.VersionInfo(version_name="2.5.0", build_number="18")
    assert br.windows_installer_name(v) == "OneTJSetup_windows_2.5.0_18.exe"


def test_android_apk_name():
    v = br.VersionInfo(version_name="2.5.0", build_number="18")
    assert br.android_apk_name(v) == "OneTJ_release_2.5.0_18.APK"


def test_naming_requires_build_number():
    v = br.VersionInfo(version_name="2.5.0", build_number="")
    with pytest.raises(ValueError):
        br.windows_installer_name(v)
    with pytest.raises(ValueError):
        br.android_apk_name(v)


# ---------------------------------------------------------------------------
# setup.iss 解析
# ---------------------------------------------------------------------------

def test_parse_setup_iss():
    text = "AppVersion=2.5.0\nOutputDir=dist\nOutputBaseFilename=OneTJSetup\n"
    parsed = br.parse_setup_iss(text)
    assert parsed["AppVersion"] == "2.5.0"
    assert parsed["OutputDir"] == "dist"
    assert parsed["OutputBaseFilename"] == "OneTJSetup"


def test_parse_setup_iss_missing_fields():
    parsed = br.parse_setup_iss("AppName=OneTJ\n")
    assert parsed["AppVersion"] is None
    assert parsed["OutputBaseFilename"] is None


# ---------------------------------------------------------------------------
# ISCC 定位
# ---------------------------------------------------------------------------

def test_iscc_candidates_prefer_which(monkeypatch):
    monkeypatch.setattr(
        br.shutil, "which",
        lambda name: "C:/tools/ISCC.exe" if name == "ISCC" else None,
    )
    cands = br.iscc_candidates()
    assert cands[0] == "C:/tools/ISCC.exe"
    assert len(cands) >= 2  # PATH 命中 + 标准目录兜底


def test_iscc_candidates_include_standard_roots(monkeypatch):
    monkeypatch.setattr(br.shutil, "which", lambda name: None)
    monkeypatch.setattr(
        br, "_iscc_standard_roots",
        lambda: [Path("X:/Program Files (x86)"), Path("X:/Program Files")],
    )
    cands = [Path(c) for c in br.iscc_candidates()]
    assert Path("X:/Program Files (x86)/Inno Setup 6/ISCC.exe") in cands
    assert Path("X:/Program Files/Inno Setup 6/ISCC.exe") in cands


def test_resolve_iscc_picks_existing():
    root = _tmp_dir("iscc")
    try:
        fake = root / "ISCC.exe"
        fake.write_bytes(b"")
        resolved = br.resolve_iscc([str(root / "missing.exe"), str(fake)])
        assert resolved == fake
        assert br.resolve_iscc([str(root / "missing.exe")]) is None
    finally:
        _cleanup(root)


# ---------------------------------------------------------------------------
# APK 探测
# ---------------------------------------------------------------------------

def test_detect_apk_files():
    root = _tmp_dir("apk")
    try:
        d = root / "flutter-apk"
        d.mkdir()
        (d / "app-release.apk").write_bytes(b"x")
        (d / "app-debug.apk").write_bytes(b"x")
        (d / "readme.txt").write_text("nope", encoding="utf-8")
        apks = br.detect_apk_files(d)
        assert [p.name for p in apks] == ["app-debug.apk", "app-release.apk"]
        assert br.detect_apk_files(root / "not-exist") == []
    finally:
        _cleanup(root)


# ---------------------------------------------------------------------------
# 配置文件加载
# ---------------------------------------------------------------------------

def test_load_config_file_missing():
    assert br.load_config_file(_PROJECT_ROOT / "config" / "no_such_file.json") == {}


def test_load_config_file_valid():
    root = _tmp_dir("cfg")
    try:
        p = root / "release_config.json"
        p.write_text(json.dumps({"repo": "R", "download_base": "https://x/downloads"}), encoding="utf-8")
        cfg = br.load_config_file(p)
        assert cfg["repo"] == "R"
        assert cfg["download_base"] == "https://x/downloads"
    finally:
        _cleanup(root)


def test_load_config_file_invalid_json():
    root = _tmp_dir("cfgbad")
    try:
        p = root / "bad.json"
        p.write_text("{not json", encoding="utf-8")
        with pytest.raises(ValueError):
            br.load_config_file(p)
    finally:
        _cleanup(root)


# ---------------------------------------------------------------------------
# build_plan 集成（fake 仓库）
# ---------------------------------------------------------------------------

def _make_fake_repo(root: Path) -> Path:
    repo = root / "onetj"
    (repo / "android" / "app").mkdir(parents=True)
    (repo / "build" / "app" / "outputs").mkdir(parents=True)
    (repo / "build" / "windows" / "x64" / "runner").mkdir(parents=True)
    (repo / "dist").mkdir()
    (repo / "pubspec.yaml").write_text("name: onetj\nversion: 2.5.0+18\n", encoding="utf-8")
    (repo / "setup.iss").write_text(
        "AppVersion=2.5.0\nOutputDir=dist\nOutputBaseFilename=OneTJSetup\n",
        encoding="utf-8",
    )
    (repo / "android" / "key.properties").write_text(
        "storeFile=OneTJ.jks\nkeyAlias=OneTJ\n", encoding="utf-8"
    )
    (repo / "android" / "app" / "OneTJ.jks").write_bytes(b"jks")
    apk_dir = repo / "build" / "app" / "outputs" / "flutter-apk"
    apk_dir.mkdir(parents=True)
    (apk_dir / "app-release.apk").write_bytes(b"apk")
    return repo


# ---------------------------------------------------------------------------
# 真实模式：产物定位 / 收集 / manifest 生成
# ---------------------------------------------------------------------------

def test_find_android_source_prefers_app_release():
    root = _tmp_dir("findapk")
    try:
        d = root / "flutter-apk"
        d.mkdir()
        (d / "app-release.apk").write_bytes(b"raw")
        (d / "OneTJ_release_2.5.0_18.APK").write_bytes(b"renamed")
        assert br.find_android_source(d, "OneTJ_release_2.5.0_18.APK").name == "app-release.apk"
    finally:
        _cleanup(root)


def test_find_android_source_falls_back_to_renamed():
    root = _tmp_dir("findapk2")
    try:
        d = root / "flutter-apk"
        d.mkdir()
        (d / "OneTJ_release_2.5.0_18.APK").write_bytes(b"renamed")
        assert br.find_android_source(d, "OneTJ_release_2.5.0_18.APK").name == "OneTJ_release_2.5.0_18.APK"
    finally:
        _cleanup(root)


def test_find_android_source_ambiguous_raises():
    root = _tmp_dir("findapk3")
    try:
        d = root / "flutter-apk"
        d.mkdir()
        (d / "a.apk").write_bytes(b"a")
        (d / "b.apk").write_bytes(b"b")
        with pytest.raises(RuntimeError):
            br.find_android_source(d, "OneTJ_release_2.5.0_18.APK")
    finally:
        _cleanup(root)


def test_find_windows_source_iss_output_first():
    root = _tmp_dir("findiss")
    try:
        dist = root / "dist"
        dist.mkdir()
        raw = dist / "OneTJSetup.exe"
        raw.write_bytes(b"raw")
        (dist / "OneTJSetup_windows_2.5.0_18.exe").write_bytes(b"renamed")
        got = br.find_windows_source(raw, dist, "OneTJSetup_windows_2.5.0_18.exe")
        assert got == raw
    finally:
        _cleanup(root)


def test_collect_platform_artifact_copies_and_renames():
    root = _tmp_dir("collect")
    try:
        repo = _make_fake_repo(root)
        plan = br.build_plan(repo, None, ["windows", "android"], _release_cfg(root))
        for pp in plan.platforms:
            # 无条件写入测试内容，确保收集比对的是确定数据
            if pp.raw_artifact is not None:
                pp.raw_artifact.write_bytes(b"artifact-data")
        for pp in plan.platforms:
            br.collect_platform_artifact(pp)
            assert pp.final_artifact.is_file()
            assert pp.final_artifact.read_bytes() == b"artifact-data"
    finally:
        _cleanup(root)


def test_build_manifest_payload_fields():
    root = _tmp_dir("payload")
    try:
        repo = _make_fake_repo(root)
        cfg = _release_cfg(root, mandatory=True, min_supported_version="2.0.0")
        plan = br.build_plan(repo, None, ["android"], cfg)
        payload = br.build_manifest_payload(plan)
        entry = payload["entries"]["android:default"]
        assert entry["version"] == "2.5.0"
        assert entry["build"] == 18
        assert entry["mandatory"] is True
        assert entry["min_supported_version"] == "2.0.0"
        assert entry["download_url"].endswith("OneTJ_release_2.5.0_18.APK")
        assert entry["release_notes_file"].endswith("notes.md")
    finally:
        _cleanup(root)


def test_write_manifest_file_computes_sha256():
    import hashlib

    root = _tmp_dir("wmanifest")
    try:
        repo = _make_fake_repo(root)
        plan = br.build_plan(repo, None, ["android"], _release_cfg(root))
        andr = next(p for p in plan.platforms)
        andr.final_artifact.parent.mkdir(parents=True, exist_ok=True)
        andr.final_artifact.write_bytes(b"hello")
        # generate_manifest_from_dict 要求 release_notes_file 真实存在
        (root / "notes.md").write_text("更新说明", encoding="utf-8")
        payload = br.build_manifest_payload(plan)
        out = root / "out" / "update_manifest.json"
        br.write_manifest_file(payload, out)
        data = json.loads(out.read_text(encoding="utf-8"))
        entry = data["android:default"]
        assert entry["latest_version"] == "2.5.0"
        assert entry["latest_build"] == 18
        assert entry["sha256"] == hashlib.sha256(b"hello").hexdigest()
        assert entry["file_size"] == 5
    finally:
        _cleanup(root)


def test_build_plan_full():
    root = _tmp_dir("plan")
    try:
        repo = _make_fake_repo(root)
        plan = br.build_plan(repo, None, ["windows", "android"], _release_cfg(root))

        assert plan.version.version_name == "2.5.0"
        assert plan.version.build_number == "18"
        assert plan.signing["key_properties_exists"] is True
        assert plan.signing["jks_found"], "应能定位 android/app/OneTJ.jks"
        assert plan.iss_drift == [], "fake setup.iss AppVersion 与 pubspec 一致时不应有漂移"

        keys = [p.key for p in plan.platforms]
        assert "windows:x64" in keys and "android:default" in keys

        win = next(p for p in plan.platforms if p.key == "windows:x64")
        assert win.final_artifact.name == "OneTJSetup_windows_2.5.0_18.exe"
        assert win.download_url == "https://example.com/downloads/OneTJSetup_windows_2.5.0_18.exe"

        andr = next(p for p in plan.platforms if p.key == "android:default")
        assert andr.final_artifact.name == "OneTJ_release_2.5.0_18.APK"
        assert andr.download_url == "https://example.com/downloads/OneTJ_release_2.5.0_18.APK"
        assert andr.build_cmds[0] == "cd /d " + str(repo)
    finally:
        _cleanup(root)


def test_build_plan_download_url_empty_without_base():
    root = _tmp_dir("nobase")
    try:
        repo = _make_fake_repo(root)
        plan = br.build_plan(repo, None, ["android"], _release_cfg(root, download_base=""))
        andr = next(p for p in plan.platforms)
        assert andr.download_url == ""
        assert any("下载基址" in w for w in plan.warnings)
    finally:
        _cleanup(root)


def test_build_plan_iscc_override():
    root = _tmp_dir("iscc2")
    try:
        repo = _make_fake_repo(root)
        fake_iscc = root / "ISCC.exe"
        fake_iscc.write_bytes(b"")
        plan = br.build_plan(
            repo, None, ["windows"],
            _release_cfg(root, iscc_override=str(fake_iscc)),
        )
        win = next(p for p in plan.platforms)
        assert win.iss_cmd is not None and "ISCC.exe" in win.iss_cmd
    finally:
        _cleanup(root)


def test_build_plan_manifest_compare():
    root = _tmp_dir("cmp")
    try:
        repo = _make_fake_repo(root)
        # 预置现网 manifest：android 已是 2.5.0/18，windows 是旧版
        mpath = root / "manifest.json"
        mpath.write_text(json.dumps({
            "android:default": {"latest_version": "2.5.0", "latest_build": 18},
            "windows:x64": {"latest_version": "2.4.4", "latest_build": 16},
        }), encoding="utf-8")
        plan = br.build_plan(repo, None, ["windows", "android"], _release_cfg(root))
        joined = "\n".join(plan.manifest_compare)
        assert "已是 2.5.0/18" in joined, "android 持平应提示幂等"
        assert "现网 manifest[windows:x64] 为 2.4.4/16" in joined
    finally:
        _cleanup(root)


def test_build_plan_missing_key_properties():
    root = _tmp_dir("nokey")
    try:
        repo = root / "onetj"
        (repo / "android").mkdir(parents=True)
        (repo / "pubspec.yaml").write_text("version: 2.5.0+18\n", encoding="utf-8")
        plan = br.build_plan(repo, None, ["android"], _release_cfg(root))
        assert plan.signing["key_properties_exists"] is False
    finally:
        _cleanup(root)


def test_build_plan_missing_pubspec():
    root = _tmp_dir("nopub")
    try:
        with pytest.raises(ValueError):
            br.build_plan(root / "nope-repo", None, ["android"], _release_cfg(root))
    finally:
        _cleanup(root)

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OneTJ 发布构建脚本

目标：输入 OneTJ 仓库路径，自动完成
    仓库定位 -> 版本解析(pubspec) -> 构建(fvm) -> 产物收集/命名 -> 生成 update_manifest.json

设计：release_spec.json 已退役。发布输入收敛为：
    - flag：--repo / --platform / --version / --mandatory / --min-supported / --download-base / --iscc / --release-notes
    - 配置：config/release_config.json（提供默认值，flag 优先）
    其余（版本、产物路径、文件名、download_url）全部由脚本按约定推导。

模式：
    - 默认：真实构建。fvm 构建 -> ISCC 打包 -> 收集产物 -> 生成 update_manifest.json；
      --skip-build 跳过构建复用已有产物；--publish 可选 scp 发布。
    - --dry-run：发布前预览。只读检查、推演命令与产物路径、对比现网 manifest，
      不做任何构建/复制/写文件操作（版本探针 `where` 类命令除外，无副作用）。

用法：
    .venv\\Scripts\\python scripts\\build_release.py [--repo <路径>] [--platform windows,android]   # 真实构建
    .venv\\Scripts\\python scripts\\build_release.py --dry-run [...]                                 # 预览

说明：
    - 默认 repo 取 config/release_config.json 的 repo 字段（缺省 E:/Program/FlutterProgram/onetj）。
    - flutter 一律通过 fvm 调用（`fvm flutter ...`），未找到 fvm 会给出告警。
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# 默认值（可用 config/release_config.json 或 flag 覆盖）
DEFAULT_REPO = "E:/Program/FlutterProgram/onetj"
DEFAULT_CONFIG = PROJECT_ROOT / "config" / "release_config.json"
DEFAULT_OUTPUT_MANIFEST = PROJECT_ROOT / "config" / "update_manifest.json"
DEFAULT_RELEASE_NOTES = PROJECT_ROOT / "release-notes" / "release.md"

# 平台 key -> 产物命名与构建命令约定
PLATFORMS = {
    "windows": {
        "key": "windows:x64",
        "build_cmds": ["fvm flutter build windows --release"],
        "iss_cmd": None,  # 运行时补全：ISCC setup.iss
        # 构建产物来源（相对仓库），用于干跑时检查"是否已有旧产物"
        "source_dirs": [Path("build/windows/x64/runner/Release")],
        # ISCC 输出（setup.iss OutputDir/OutputBaseFilename 以解析结果为准，此处为兜底）
        "iss_output_dir": Path("dist"),
        "iss_output_base": "OneTJSetup",
    },
    "android": {
        "key": "android:default",
        "build_cmds": ["fvm flutter build apk --release"],
        "iss_cmd": None,
        "source_dirs": [Path("build/app/outputs/flutter-apk")],
        "apk_output_name": "app-release.apk",
    },
}


@dataclass(frozen=True)
class VersionInfo:
    version_name: str  # 2.5.0
    build_number: str  # 18


@dataclass(frozen=True)
class ReleaseConfig:
    """发布配置（合并 config/release_config.json 与 CLI flag 后的结果）。"""

    collect_dir: Path
    download_base: str
    iscc_override: str | None
    release_notes_file: Path | None
    mandatory: bool
    min_supported_version: str | None
    output_manifest: Path
    publish_dir: str | None = None  # 服务器项目部署目录，如 user@host:/opt/OneTJ-Analytics；派生子目录 downloads/ 与 config/
    reload_cmd: str | None = None  # 发布后执行的 API 重载命令
    publish_ignore: str | None = None  # 发布时跳过列出的文件（逗号分隔，如 '.env'）


def parse_pubspec_version(text: str) -> VersionInfo:
    """从 pubspec.yaml 文本解析 version: <major>.<minor>.<patch>(+<build>)?"""
    m = re.search(
        r"^version:\s*([0-9]+\.[0-9]+\.[0-9]+)(?:\+([0-9]+))?\s*$",
        text,
        re.MULTILINE,
    )
    if not m:
        raise ValueError(
            "pubspec.yaml 中未找到合法的 version 行，期望 <major>.<minor>.<patch>(+<build>)?"
        )
    return VersionInfo(version_name=m.group(1), build_number=m.group(2) or "")


def _require_build(v: VersionInfo) -> None:
    if not v.build_number:
        raise ValueError(
            "pubspec 未提供构建号（version 形如 2.5.0+18），无法推演产物命名，请用 --version <x.y.z+b> 覆盖"
        )


def windows_installer_name(v: VersionInfo) -> str:
    """推演 Windows 安装包最终文件名：OneTJSetup_windows_<v>_<b>.exe"""
    _require_build(v)
    return f"OneTJSetup_windows_{v.version_name}_{v.build_number}.exe"


def android_apk_name(v: VersionInfo) -> str:
    """推演 Android APK 最终文件名：OneTJ_release_<v>_<b>.APK"""
    _require_build(v)
    return f"OneTJ_release_{v.version_name}_{v.build_number}.APK"


def parse_setup_iss(text: str) -> dict[str, str | None]:
    """从 setup.iss 提取 AppVersion / OutputDir / OutputBaseFilename（供漂移检测）"""
    out: dict[str, str | None] = {}
    for key in ("AppVersion", "OutputDir", "OutputBaseFilename"):
        m = re.search(rf"^{key}=(.+)$", text, re.MULTILINE)
        out[key] = m.group(1).strip() if m else None
    return out


def _iscc_standard_roots() -> list[Path]:
    """Inno Setup 可能的安装根目录（环境变量指定 + 所有存在的固定盘符）。

    默认只查环境变量指向的 Program Files 不够通用——Inno 可能装在
    E:/D: 等其他盘（本机即在 E 盘）。这里把所有存在盘符的
    \\Program Files (x86)\\ 与 \\Program Files\\ 都纳入候选。
    """
    roots: list[Path] = []
    for env_name, default in (
        ("ProgramFiles(x86)", r"C:\Program Files (x86)"),
        ("ProgramFiles", r"C:\Program Files"),
    ):
        roots.append(Path(os.environ.get(env_name, default)))
    for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        drive = Path(f"{letter}:\\")
        try:
            if not drive.exists():
                continue
        except OSError:
            continue  # 无介质的光驱/网络盘等
        for sub in ("Program Files (x86)", "Program Files"):
            roots.append(drive / sub)
    # 去重保序
    return list(dict.fromkeys(roots))


def iscc_candidates() -> list[str]:
    """收集可能的 ISCC.exe 路径（PATH + 标准安装目录，含跨盘扫描）"""
    candidates: list[str] = []
    found = shutil.which("ISCC")
    if found:
        candidates.append(found)
    for root in _iscc_standard_roots():
        candidates.append(str(root / "Inno Setup 6" / "ISCC.exe"))
    # 去重保序
    return list(dict.fromkeys(candidates))


def resolve_iscc(candidates: list[str]) -> Path | None:
    for c in candidates:
        p = Path(c)
        if p.is_file():
            return p
    return None


def detect_apk_files(apk_dir: Path) -> list[Path]:
    """列出 flutter-apk 目录下现有 .apk 文件（用于告诉用户当前已有哪些产物）"""
    if not apk_dir.is_dir():
        return []
    return sorted(p for p in apk_dir.iterdir() if p.suffix.lower() == ".apk")


def check_tool(name: str, required: bool = False) -> dict[str, Any]:
    found = shutil.which(name)
    return {
        "name": name,
        "found": found is not None,
        "path": found,
        "required": required,
    }


def load_config_file(path: Path) -> dict[str, Any]:
    """读取 release_config.json；文件不存在返回空 dict，解析失败报错。"""
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise ValueError(f"配置文件解析失败: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"配置文件必须是 JSON 对象: {path}")
    return payload


@dataclass
class PlatformPlan:
    key: str
    platform: str
    build_cmds: list[str]
    iss_cmd: str | None
    source_dirs: list[Path]
    final_artifact: Path
    download_url: str
    existing_sources: list[Path]
    # 真实模式收集用：构建产出的原始文件（可能不存在）+ 回退扫描目录
    raw_artifact: Path | None = None
    fallback_dir: Path | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "platform": self.platform,
            "build_cmds": self.build_cmds,
            "iss_cmd": self.iss_cmd,
            "source_dirs": [str(p) for p in self.source_dirs],
            "final_artifact": str(self.final_artifact),
            "download_url": self.download_url,
            "existing_sources": [str(p) for p in self.existing_sources],
            "raw_artifact": str(self.raw_artifact) if self.raw_artifact else None,
            "fallback_dir": str(self.fallback_dir) if self.fallback_dir else None,
            "notes": self.notes,
        }


@dataclass
class BuildPlan:
    repo: Path
    version: VersionInfo
    version_override: bool
    release_cfg: ReleaseConfig
    tools: list[dict[str, Any]]
    setup_iss: dict[str, str | None]
    iss_drift: list[str]
    signing: dict[str, Any]
    platforms: list[PlatformPlan]
    manifest_compare: list[str]
    warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "repo": str(self.repo),
            "version_name": self.version.version_name,
            "build_number": self.version.build_number,
            "version_override": self.version_override,
            "release_config": {
                "collect_dir": str(self.release_cfg.collect_dir),
                "download_base": self.release_cfg.download_base,
                "iscc_override": self.release_cfg.iscc_override,
                "release_notes_file": str(self.release_cfg.release_notes_file)
                if self.release_cfg.release_notes_file
                else None,
                "mandatory": self.release_cfg.mandatory,
                "min_supported_version": self.release_cfg.min_supported_version,
                "output_manifest": str(self.release_cfg.output_manifest),
            },
            "tools": self.tools,
            "setup_iss": self.setup_iss,
            "iss_drift": self.iss_drift,
            "signing": self.signing,
            "platforms": [p.to_dict() for p in self.platforms],
            "manifest_compare": self.manifest_compare,
            "warnings": self.warnings,
        }


def _parse_version_override(raw: str | None) -> VersionInfo | None:
    if raw is None:
        return None
    return parse_pubspec_version(f"version: {raw}")


def build_plan(
    repo: Path,
    version_override: VersionInfo | None,
    platforms: list[str],
    release_cfg: ReleaseConfig,
) -> BuildPlan:
    warnings: list[str] = []
    manifest_compare: list[str] = []

    # ---- 仓库与 pubspec ----
    if not repo.is_dir():
        raise ValueError(f"仓库路径不存在或不是目录: {repo}")
    pubspec_path = repo / "pubspec.yaml"
    if not pubspec_path.is_file():
        raise ValueError(f"仓库中未找到 pubspec.yaml: {pubspec_path}")

    version = version_override or parse_pubspec_version(
        pubspec_path.read_text(encoding="utf-8")
    )

    # ---- 工具链检查 ----
    tools = [
        check_tool("fvm", required=True),       # flutter 必须走 fvm
        check_tool("flutter"),                  # 兜底参考
        check_tool("ISCC"),                     # Inno Setup 编译器
    ]
    if not tools[0]["found"]:
        warnings.append("未找到 fvm（flutter 版本管理），构建命令将不可用")
    fvm_state = "已找到" if tools[0]["found"] else "缺失"
    tools[0]["note"] = f"flutter 将通过 fvm 调用 [{fvm_state}]"

    # ---- ISCC 定位（显式配置优先，否则自动探测）----
    iscc_path: Path | None = None
    if release_cfg.iscc_override:
        p = Path(release_cfg.iscc_override)
        if p.is_file():
            iscc_path = p
        else:
            warnings.append(f"配置的 ISCC 路径不存在: {p}（安装包步骤将跳过）")
    else:
        iscc_path = resolve_iscc(iscc_candidates())
    if iscc_path is None and not release_cfg.iscc_override:
        warnings.append("ISCC.exe 未在 PATH 与标准安装目录找到，Windows 安装包将无法自动打包")
    if iscc_path is not None:
        tools[2]["found"] = True
        tools[2]["path"] = str(iscc_path)
        tools[2]["note"] = "配置指定" if release_cfg.iscc_override else "自动探测（跨盘扫描）"

    # ---- 下载基址 / release notes 检查 ----
    if not release_cfg.download_base:
        warnings.append("未配置下载基址（release_config.json 的 download_base 或 --download-base），download_url 将为空")
    rn = release_cfg.release_notes_file
    if rn is not None and not rn.is_file():
        warnings.append(f"release notes 文件不存在: {rn}")

    # ---- 现网 manifest 读取（用于对比"本次发布 vs 现网"）----
    current_manifest: dict[str, Any] = {}
    mpath = release_cfg.output_manifest
    if mpath.is_file():
        try:
            current_manifest = json.loads(mpath.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            current_manifest = {}

    # ---- setup.iss（Windows 侧）----
    setup_iss_path = repo / "setup.iss"
    setup_iss: dict[str, str | None] = {"path": str(setup_iss_path)}
    iss_drift: list[str] = []
    if setup_iss_path.is_file():
        setup_iss.update(parse_setup_iss(setup_iss_path.read_text(encoding="utf-8")))
        app_ver = setup_iss.get("AppVersion")
        if app_ver is not None and app_ver != version.version_name:
            iss_drift.append(
                f"setup.iss AppVersion={app_ver} 与 pubspec version {version.version_name} 不一致（发布前请先运行 OneTJ 的 update_app_version 脚本）"
            )
    else:
        iss_drift.append(f"仓库缺失 setup.iss: {setup_iss_path}")

    # ---- Android 签名检查（只报存在性，不读内容：key.properties 含明文口令）----
    keyprops = repo / "android" / "key.properties"
    signing: dict[str, Any] = {
        "key_properties_exists": keyprops.is_file(),
    }
    if keyprops.is_file():
        props: dict[str, str] = {}
        for line in keyprops.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                props[k.strip()] = v.strip()
        store_file = props.get("storeFile")
        jks_candidates = [
            repo / "android" / "app" / store_file,
            repo / "android" / store_file,
            repo / store_file,
        ] if store_file else []
        jks_found = [str(p) for p in jks_candidates if p.is_file()]
        signing.update(
            {
                "storefile_configured": bool(store_file),
                "jks_found": jks_found,
                "note": "key.properties 包含明文口令，脚本不会读取/打印其内容",
            }
        )
        if store_file and not jks_found:
            warnings.append(
                f"key.properties 配置了 storeFile={store_file}，但在 android/app、android、仓库根均未找到该 jks 文件"
            )
    else:
        signing["note"] = "android/key.properties 不存在，flutter build apk --release 将产出未签名的 app-release.apk"

    # ---- 逐平台推演 ----
    planned: list[PlatformPlan] = []
    for platform in platforms:
        cfg = PLATFORMS[platform]
        key = cfg["key"]
        final_name = (
            windows_installer_name(version)
            if platform == "windows"
            else android_apk_name(version)
        )
        final_artifact = release_cfg.collect_dir / final_name
        download_url = (
            f"{release_cfg.download_base.rstrip('/')}/{final_name}"
            if release_cfg.download_base
            else ""
        )

        build_cmds = list(cfg["build_cmds"])
        iss_cmd: str | None = None
        notes: list[str] = []
        source_dirs = [repo / d for d in cfg["source_dirs"]]
        raw_artifact: Path | None = None
        fallback_dir: Path | None = None

        if platform == "windows":
            iss_output = (
                repo
                / (setup_iss.get("OutputDir") or str(cfg["iss_output_dir"]))
                / f"{setup_iss.get('OutputBaseFilename') or cfg['iss_output_base']}.exe"
            ).resolve()
            raw_artifact = iss_output
            fallback_dir = repo / (setup_iss.get("OutputDir") or str(cfg["iss_output_dir"]))
            if iscc_path is not None:
                iss_cmd = f'"{iscc_path}" setup.iss'
                build_cmds.append(iss_cmd)
                notes.append(f"ISCC 预期输出: {iss_output}（构建后需重命名为 {final_name}）")
                if iss_output.is_file():
                    existing = [iss_output]
                elif fallback_dir.is_dir():
                    existing = sorted(
                        p for p in fallback_dir.iterdir()
                        if p.suffix.lower() == ".exe"
                    )
                else:
                    existing = []
                if existing:
                    notes.append(
                        "已存在同名旧产物，真实构建前请确认（脚本默认会先重命名再复制，可覆盖）"
                    )
            else:
                notes.append("未找到 ISCC.exe，跳过安装包打包步骤（仅 flutter build windows）")
            build_cmds.insert(0, "cd /d " + str(repo))  # Windows 下定位到仓库执行
        else:
            existing = detect_apk_files(source_dirs[0])
            if existing:
                names = ", ".join(p.name for p in existing)
                notes.append(f"flutter-apk 目录已存在: {names}")
            raw_artifact = source_dirs[0] / cfg["apk_output_name"]
            fallback_dir = source_dirs[0]
            if not raw_artifact.is_file() and existing:
                notes.append(
                    f"未找到默认输出 {cfg['apk_output_name']}（可能已被改名/清理）；构建后请以该路径或 glob 唯一匹配为准"
                )
            build_cmds.insert(0, "cd /d " + str(repo))

        # ---- 现网 manifest 对比 ----
        cur = current_manifest.get(key)
        if isinstance(cur, dict) and "latest_version" in cur:
            cv = cur.get("latest_version")
            cb = cur.get("latest_build")
            if cv == version.version_name and str(cb) == version.build_number:
                manifest_compare.append(f"现网 manifest[{key}] 已是 {cv}/{cb}（本次发布持平，注意幂等）")
            else:
                manifest_compare.append(
                    f"现网 manifest[{key}] 为 {cv}/{cb}，本次将发布 {version.version_name}/{version.build_number}"
                )
        else:
            manifest_compare.append(f"现网 manifest 无 {key} 条目，本次为新增发布")

        planned.append(
            PlatformPlan(
                key=key,
                platform=platform,
                build_cmds=build_cmds,
                iss_cmd=iss_cmd,
                source_dirs=source_dirs,
                final_artifact=final_artifact,
                download_url=download_url,
                existing_sources=[
                    p
                    for d in source_dirs
                    if d.is_dir()
                    for p in sorted(d.iterdir())
                    if p.is_file() and p.suffix.lower() in {".exe", ".apk", ".dll"}
                ],
                raw_artifact=raw_artifact,
                fallback_dir=fallback_dir,
                notes=notes,
            )
        )

    return BuildPlan(
        repo=repo,
        version=version,
        version_override=version_override is not None,
        release_cfg=release_cfg,
        tools=tools,
        setup_iss=setup_iss,
        iss_drift=iss_drift,
        signing=signing,
        platforms=planned,
        manifest_compare=manifest_compare,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# 报告输出
# ---------------------------------------------------------------------------

def _run_cmd(cmd: str, cwd: Path, label: str) -> None:
    """执行一条命令（shell 展开，输出直通终端）。"""
    print(f">>> [{label}] {cmd}  (cwd={cwd})", flush=True)
    proc = subprocess.run(cmd, cwd=str(cwd), shell=True)
    if proc.returncode != 0:
        raise RuntimeError(f"[{label}] 命令失败 (exit={proc.returncode}): {cmd}")
    return None


def find_android_source(apk_dir: Path, final_name: str) -> Path:
    """定位 Android 原始产物：app-release.apk -> 恰好同名的成品 -> 唯一候选。"""
    if not apk_dir.is_dir():
        raise FileNotFoundError(f"android 产物目录不存在: {apk_dir}")
    raw = apk_dir / "app-release.apk"
    if raw.is_file():
        return raw
    exact = apk_dir / final_name
    if exact.is_file():
        return exact
    candidates = [
        p for p in apk_dir.iterdir()
        if p.suffix.lower() == ".apk"
        and "debug" not in p.name.lower()
        and "profile" not in p.name.lower()
    ]
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        raise RuntimeError(f"android 产物不唯一: {[p.name for p in candidates]}，请清理后重试")
    raise FileNotFoundError(
        f"未找到 android 产物（app-release.apk 或 {final_name}）于 {apk_dir}"
    )


def find_windows_source(iss_output: Path, fallback_dir: Path, final_name: str) -> Path:
    """定位 Windows 原始产物：ISCC 输出 -> 恰好同名的成品。"""
    if iss_output.is_file():
        return iss_output
    exact = fallback_dir / final_name
    if exact.is_file():
        return exact
    raise FileNotFoundError(
        f"未找到 Windows 产物（{iss_output} 或 {exact}），请先完成构建/打包"
    )


def collect_platform_artifact(pp: PlatformPlan) -> Path:
    """把平台原始产物复制（重命名）到最终收集位置。"""
    src: Path | None = None
    if pp.raw_artifact is not None and pp.raw_artifact.is_file():
        src = pp.raw_artifact
    elif pp.platform == "android" and pp.fallback_dir is not None:
        src = find_android_source(pp.fallback_dir, pp.final_artifact.name)
    elif (
        pp.platform == "windows"
        and pp.raw_artifact is not None
        and pp.fallback_dir is not None
    ):
        src = find_windows_source(pp.raw_artifact, pp.fallback_dir, pp.final_artifact.name)
    if src is None:
        raise FileNotFoundError(f"{pp.key}: 缺少产物定位信息（raw_artifact/fallback_dir）")
    pp.final_artifact.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, pp.final_artifact)
    print(
        f"  收集: {src} -> {pp.final_artifact} ({pp.final_artifact.stat().st_size} bytes)",
        flush=True,
    )
    return pp.final_artifact


def build_manifest_payload(plan: BuildPlan) -> dict[str, Any]:
    """根据计划构造发布规格 payload（直接交给 generate_manifest_from_dict）。"""
    payload: dict[str, Any] = {"entries": {}}
    for pp in plan.platforms:
        entry: dict[str, Any] = {
            "version": plan.version.version_name,
            "build": int(plan.version.build_number),
            "artifact_path": str(pp.final_artifact),
            "download_url": pp.download_url,
        }
        rn = plan.release_cfg.release_notes_file
        if rn is not None:
            entry["release_notes_file"] = str(rn)
        if plan.release_cfg.mandatory:
            entry["mandatory"] = True
        if plan.release_cfg.min_supported_version:
            entry["min_supported_version"] = plan.release_cfg.min_supported_version
        payload["entries"][pp.key] = entry
    return payload


def write_manifest_file(payload: dict[str, Any], output_path: Path) -> Path:
    """复用底层工具的校验/计算逻辑，写出 update_manifest.json。"""
    scripts_dir = str(PROJECT_ROOT / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    from generate_update_manifest import generate_manifest_from_dict

    manifest = generate_manifest_from_dict(payload, PROJECT_ROOT)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="\n") as fp:
        json.dump(
            manifest.model_dump(mode="json")["entries"],
            fp,
            ensure_ascii=False,
            indent=2,
        )
        fp.write("\n")
    return output_path


def publish_artifacts(plan: BuildPlan, publish_dir: str, ignore: str) -> None:
    """发布产物到 <publish_dir>/downloads/，manifest 及 config 到 <publish_dir>/config/。"""
    base = publish_dir.rstrip("/")

    # 1) 产物 -> <publish_dir>/downloads/
    dl = f"{base}/downloads"
    for pp in plan.platforms:
        cmd = f'scp "{pp.final_artifact}" {dl}/'
        _run_cmd(cmd, PROJECT_ROOT, f"发布 {pp.key}")
        print(f"  已发布，核对 URL: {pp.download_url}", flush=True)

    # 2) manifest + config -> <publish_dir>/config/
    ignore_names = {n.strip() for n in ignore.split(",") if n.strip()}
    cfg_dir = plan.release_cfg.output_manifest.parent
    for name in sorted(p.name for p in cfg_dir.iterdir() if p.is_file()):
        if name in ignore_names:
            print(f"  跳过发布（忽略）: config/{name}", flush=True)
            continue
        f = cfg_dir / name
        cmd = f'scp "{f}" {base}/config/'
        _run_cmd(cmd, PROJECT_ROOT, f"发布 config/{name}")
    print(f"  已发布 manifest 到: {base}/config/", flush=True)


def reload_api(plan: BuildPlan, reload_cmd: str | None, host: str | None) -> None:
    """在服务器上执行 API 重载命令。"""
    if not reload_cmd:
        print("  未配置 reload_cmd，跳过 API 重载（请手动重启 API 以加载新 manifest）", flush=True)
        return
    if not host:
        print("  未配置 SSH host（从 publish_dir 解析失败），跳过 API 重载", flush=True)
        return
    cmd = f'ssh {host} "{reload_cmd}"'
    _run_cmd(cmd, PROJECT_ROOT, "重载 API")
    print(f"  API 已重载: {reload_cmd}", flush=True)


def run_release(plan: BuildPlan, skip_build: bool, publish: bool, reload_api_flag: bool) -> int:
    print("==== OneTJ 发布构建（真实模式）====")
    print(f"仓库: {plan.repo}")
    print(f"版本: {plan.version.version_name}+{plan.version.build_number}")

    fvm_ok = any(t["name"] == "fvm" and t["found"] for t in plan.tools)
    if not fvm_ok:
        raise RuntimeError("未找到 fvm，无法执行 flutter 构建（请先安装/配置 fvm）")

    # 1) 构建
    if skip_build:
        print("--skip-build：跳过构建，直接收集已有产物。")
    else:
        for pp in plan.platforms:
            for cmd in pp.build_cmds:
                if cmd.startswith("cd /d "):
                    continue  # 统一用 cwd=repo 执行
                _run_cmd(cmd, plan.repo, pp.key)

    # 2) 收集产物
    print("收集产物...")
    for pp in plan.platforms:
        collect_platform_artifact(pp)

    # 3) 生成 manifest
    payload = build_manifest_payload(plan)
    out = write_manifest_file(payload, plan.release_cfg.output_manifest)
    print(f"manifest 已生成: {out}")

    # 4) 发布（可选）
    if publish:
        publish_dir = plan.release_cfg.publish_dir or ""
        if not publish_dir:
            raise RuntimeError("--publish 需要配置 publish_dir（user@host:/opt/OneTJ-Analytics）")
        publish_artifacts(plan, publish_dir, plan.release_cfg.publish_ignore or ".env")
        if reload_api_flag:
            host = publish_dir.rsplit(":", 1)[0]
            reload_api(plan, plan.release_cfg.reload_cmd, host)

    print("==== 发布构建完成 ====")
    return 0


def _yn(ok: bool) -> str:
    return "✓" if ok else "✗"


def render_plan(plan: BuildPlan) -> str:
    L: list[str] = []
    L.append("=" * 72)
    L.append("OneTJ 发布构建 · 干跑报告（DRY-RUN，未执行任何构建/复制）")
    L.append("=" * 72)

    L.append(f"\n[仓库] {plan.repo}")
    L.append(f"  pubspec version : {plan.version.version_name}+{plan.version.build_number}"
             + ("（来自 --version 覆盖）" if plan.version_override else "（读自 pubspec.yaml）"))
    L.append(f"  产物收集目录    : {plan.release_cfg.collect_dir}")

    L.append("\n[发布配置]")
    L.append(f"  下载基址        : {plan.release_cfg.download_base or '（未配置 ⚠）'}")
    L.append(f"  强制更新        : {'是' if plan.release_cfg.mandatory else '否'}")
    L.append(f"  最低支持版本    : {plan.release_cfg.min_supported_version or '（未配置）'}")
    L.append(f"  release notes   : {plan.release_cfg.release_notes_file or '（未配置）'}")
    L.append(f"  输出 manifest   : {plan.release_cfg.output_manifest}")
    L.append(f"  发布目标        : {plan.release_cfg.publish_dir or '（未配置，--publish 不可用）'}")
    if plan.release_cfg.publish_dir:
        L.append(f"    - 产物 -> {plan.release_cfg.publish_dir.rstrip('/')}/downloads/")
        L.append(f"    - manifest/config -> {plan.release_cfg.publish_dir.rstrip('/')}/config/")

    L.append("\n[工具链]")
    for t in plan.tools:
        mark = _yn(t["found"])
        extra = f"  note={t['note']}" if t.get("note") else ""
        L.append(f"  {mark} {t['name']:<12} {t['path'] or '（未找到）'}{extra}")
    if plan.release_cfg.iscc_override:
        L.append(f"  ISCC（配置指定）: {plan.release_cfg.iscc_override}")

    L.append("\n[Windows 安装包 setup.iss]")
    if plan.setup_iss.get("path"):
        L.append(f"  文件: {plan.setup_iss['path']}")
        L.append(f"  AppVersion={plan.setup_iss.get('AppVersion')}  OutputDir={plan.setup_iss.get('OutputDir')}  OutputBaseFilename={plan.setup_iss.get('OutputBaseFilename')}")
    else:
        L.append("  （缺失）")
    for d in plan.iss_drift:
        L.append(f"  ⚠ {d}")

    L.append("\n[Android 签名]")
    L.append(f"  key.properties 存在 : {_yn(plan.signing.get('key_properties_exists', False))}")
    if plan.signing.get("jks_found"):
        L.append(f"  keystore 定位       : {plan.signing['jks_found']}")
    if plan.signing.get("note"):
        L.append(f"  说明                : {plan.signing['note']}")

    for p in plan.platforms:
        L.append(f"\n[平台 {p.key}]")
        L.append("  构建指令（真实模式将依次执行，cwd=仓库）:")
        for c in p.build_cmds:
            L.append(f"    $ {c}")
        if p.iss_cmd is None and p.platform == "windows":
            L.append("    （ISCC 缺失，安装包步骤跳过）")
        L.append(f"  最终产物: {p.final_artifact}")
        L.append(f"  下载地址: {p.download_url or '（未配置基址）'}")
        for n in p.notes:
            L.append(f"  · {n}")

    L.append("\n[现网 manifest 对比]")
    for m in plan.manifest_compare:
        L.append(f"  · {m}")

    L.append("\n[告警汇总]")
    if plan.warnings:
        for w in plan.warnings:
            L.append(f"  ⚠ {w}")
    else:
        L.append("  无")

    L.append("\n" + "=" * 72)
    L.append("DRY-RUN 结束：以上均为只读检查与路径推演。确认后直接运行本命令（不加 --dry-run）即执行真实构建。")
    L.append("=" * 72)
    return "\n".join(L)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="OneTJ 发布构建：默认真实构建；加 --dry-run 仅预览"
    )
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="发布配置文件（默认 %(default)s）")
    parser.add_argument("--repo", default=None, help="OneTJ 仓库路径（缺省取配置文件 repo 字段）")
    parser.add_argument(
        "--platform",
        default="windows,android",
        help="逗号分隔的平台子集: windows,android（默认全部）",
    )
    parser.add_argument(
        "--version",
        default=None,
        help="覆盖版本，格式 <major>.<minor>.<patch>+<build>（默认读 pubspec）",
    )
    parser.add_argument("--collect-dir", default=None, help="产物收集目录（默认取配置或 dist/）")
    parser.add_argument("--download-base", default=None, help="下载基址，如 https://host/downloads")
    parser.add_argument("--iscc", default=None, help="ISCC.exe 显式路径（缺省自动探测）")
    parser.add_argument("--release-notes", default=None, help="release notes 文件路径")
    parser.add_argument("--mandatory", action="store_true", default=None, help="强制更新")
    parser.add_argument("--min-supported", default=None, help="最低支持版本 major.minor.patch")
    parser.add_argument("--output-manifest", default=None, help="输出 manifest 路径（默认 config/update_manifest.json）")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅预览：只读检查与路径推演，不执行构建/复制/写文件（默认行为是直接真实构建）",
    )
    parser.add_argument(
        "--skip-build",
        action="store_true",
        help="跳过 flutter/ISCC 构建，直接收集已有产物并生成 manifest（复用旧产物 / 快速验证）",
    )
    parser.add_argument(
        "--publish",
        action="store_true",
        help="完整发布：产物 scp 到 <publish_dir>/downloads/、manifest 到 <publish_dir>/config/（需配置 publish_dir）",
    )
    parser.add_argument(
        "--publish-dir",
        default=None,
        help="服务器项目部署目录，形如 user@host:/opt/OneTJ-Analytics；子目录 downloads/ 与 config/ 由脚本自动推导；缺省取配置 publish_dir",
    )
    parser.add_argument(
        "--reload-cmd",
        default=None,
        help="--reload-api 时在服务器执行的命令（缺省取配置 reload_cmd）",
    )
    parser.add_argument(
        "--publish-ignore",
        default=None,
        help="发布时跳过的 config 文件名（逗号分隔，如 '.env'；缺省取配置 publish_ignore 或 .env）",
    )
    parser.add_argument(
        "--reload-api",
        action="store_true",
        help="发布后通过 SSH 执行 reload_cmd 以加载新 manifest",
    )
    parser.add_argument("--json", action="store_true", help="输出 JSON 报告")
    args = parser.parse_args(argv)

    # Windows 控制台默认代码页可能不是 UTF-8，强制 UTF-8 输出避免中文乱码
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

    cfg = load_config_file(Path(args.config))

    def pick(cli_val: Any, key: str, default: Any) -> Any:
        return cli_val if cli_val is not None else cfg.get(key, default)

    repo = Path(pick(args.repo, "repo", DEFAULT_REPO)).expanduser().resolve()
    collect_raw = pick(args.collect_dir, "collect_dir", "dist")
    collect_dir = Path(collect_raw).expanduser()
    if not collect_dir.is_absolute():
        collect_dir = (PROJECT_ROOT / collect_dir).resolve()
    release_notes_raw = pick(args.release_notes, "release_notes_file", str(DEFAULT_RELEASE_NOTES))
    release_notes = Path(release_notes_raw).expanduser()
    if not release_notes.is_absolute():
        release_notes = (PROJECT_ROOT / release_notes).resolve()
    output_manifest_raw = pick(args.output_manifest, "output_manifest", str(DEFAULT_OUTPUT_MANIFEST))
    output_manifest = Path(output_manifest_raw).expanduser()
    if not output_manifest.is_absolute():
        output_manifest = (PROJECT_ROOT / output_manifest).resolve()

    release_cfg = ReleaseConfig(
        collect_dir=collect_dir,
        download_base=str(pick(args.download_base, "download_base", "")).strip(),
        iscc_override=pick(args.iscc, "iscc", None),
        release_notes_file=release_notes,
        mandatory=bool(pick(args.mandatory, "mandatory", False)),
        min_supported_version=pick(args.min_supported, "min_supported_version", None),
        output_manifest=output_manifest,
        publish_dir=pick(args.publish_dir, "publish_dir", None),
        reload_cmd=pick(args.reload_cmd, "reload_cmd", None),
        publish_ignore=pick(args.publish_ignore, "publish_ignore", ".env"),
    )

    try:
        version_override = _parse_version_override(args.version)
        platforms = [p.strip() for p in args.platform.split(",") if p.strip()]
        for p in platforms:
            if p not in PLATFORMS:
                raise ValueError(f"未知平台: {p}，可选 {', '.join(PLATFORMS)}")
        plan = build_plan(repo, version_override, platforms, release_cfg)
    except ValueError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1

    if args.dry_run:
        if args.json:
            print(json.dumps(plan.to_dict(), ensure_ascii=False, indent=2))
        else:
            print(render_plan(plan))
        # 预览模式下关键工具缺失只告警不失败
        return 0

    # 默认：真实构建
    try:
        return run_release(
            plan,
            skip_build=args.skip_build,
            publish=args.publish,
            reload_api_flag=args.reload_api,
        )
    except (RuntimeError, FileNotFoundError) as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
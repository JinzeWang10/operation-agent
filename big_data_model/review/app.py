"""复核台 Flask 后端。

与 cases.jsonl 同机、直接读文件;overlay 走 PG(经 adapters）。身份从 Authorization
头解出复核人。所有写操作只落 overlay,cases.jsonl 不动。

本地起:
    AGENT_REVIEW_DB_BACKEND=sqlite  flask --app big_data_model.review.app:create_app run
内网:改 AGENT_REVIEW_DB_BACKEND=intranet、AGENT_REVIEW_IDENTITY=intranet,建两张 PG 表。
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from flask import Flask, Response, jsonify, request

from big_data_model.incident.knowledge import normalize
from big_data_model.review import overlay as overlay_mod
from big_data_model.review import service
from big_data_model.review.adapters import identity


def create_app(cases_path: Optional[str | Path] = None) -> Flask:
    app = Flask(__name__)
    path = Path(cases_path) if cases_path else service.DEFAULT_CASES_PATH

    def _reviewer() -> str:
        return identity.reviewer_name(request.headers.get("Authorization"))

    @app.get("/api/review/cases")
    def get_cases():
        return jsonify(service.build_cases(path))

    @app.get("/api/review/meta")
    def get_meta():
        # 下拉源:类别枚举(带说明) + 系统名词表
        return jsonify(
            {"categories": service.categories(), "systems": sorted(normalize.load_known_systems())}
        )

    @app.post("/api/review/case/<event_id>")
    def save_case(event_id: str):
        body = request.get_json(force=True, silent=True) or {}
        patch = body.get("patch") or {}
        try:
            service.validate_patch(patch)
        except ValueError as e:
            return jsonify({"error": "invalid_patch", "message": str(e)}), 400
        try:
            version = overlay_mod.save_edit(
                event_id,
                patch,
                reviewed=bool(body.get("reviewed", True)),
                reviewer=_reviewer(),
                base_version=body.get("base_version"),
            )
        except overlay_mod.VersionConflict as e:
            return jsonify({"error": "version_conflict", "latest": e.latest}), 409
        return jsonify({"ok": True, "version": version})

    @app.get("/api/review/export")
    def export():
        data = service.export_reviewed(path)
        return Response(
            data,
            mimetype="application/x-ndjson",
            headers={"Content-Disposition": "attachment; filename=cases_reviewed.jsonl"},
        )

    @app.post("/api/vocab/pending")
    def add_pending():
        body = request.get_json(force=True, silent=True) or {}
        name = str(body.get("system_name", "")).strip()
        if not name:
            return jsonify({"error": "invalid", "message": "system_name 必填"}), 400
        overlay_mod.add_pending_system(name, body.get("source_event_id"), _reviewer())
        return jsonify({"ok": True})

    return app

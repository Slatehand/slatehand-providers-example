"""H3 持久提交发件箱：先返回句柄，观察时按固定标识上传和查询。

本机只保存冻结的 Provider 请求与传输回执，不读取或修改项目。没有 Core 观察的发件箱不会执行；
远端受理后删除本机媒体副本，只保留回执，远端任务丢失时不得重新生成。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import threading
from pathlib import Path
from uuid import uuid4

from core.model_providers.boundary import ModelProviderError
from core.model_providers.http import HttpResponse, HttpTransport, UrllibTransport

_ID = re.compile(r"[0-9a-f]{32}\Z")
UPLOAD_TIMEOUT = 120.0


class H3SubmissionTransport:
    def __init__(
        self, endpoint: str, mode: str, directory: Path, transport: HttpTransport | None = None
    ) -> None:
        self._endpoint = endpoint.rstrip("/")
        self._mode = mode
        self._route = f"/minimax-h3/{mode}/{'renders' if mode == 'ref2va' else 'clips'}"
        self._url = self._endpoint + self._route
        self._directory = directory
        self._http = transport or UrllibTransport()
        self._guard = threading.Lock()
        self._locks: dict[str, threading.Lock] = {}

    def request(
        self,
        method: str,
        url: str,
        *,
        json_body=None,
        content=None,
        content_type=None,
        timeout: float = 30.0,
    ) -> HttpResponse:
        if method == "POST" and url == self._url and json_body is not None:
            return self._stage(json_body)
        suffix = url.removeprefix(self._url + "/")
        task_id = suffix.removesuffix("/abort")
        if (
            url.startswith(self._url + "/")
            and _ID.fullmatch(task_id)
            and self._path(task_id).is_file()
        ):
            with self._guard:
                lock = self._locks.setdefault(task_id, threading.Lock())
            with lock:
                record = json.loads(self._path(task_id).read_text(encoding="utf-8"))
                if record["endpoint"] != self._endpoint:
                    raise ModelProviderError(
                        "invalid_handle", "H3 提交的节点地址已变化，不能转交其它节点。"
                    )
                if method == "GET" and suffix == task_id:
                    return self._observe(task_id, record)
                if (method == "DELETE" and suffix == task_id) or (
                    method == "PUT" and suffix == task_id + "/abort"
                ):
                    return self._cancel(task_id, record)
        return self._http.request(
            method,
            url,
            json_body=json_body,
            content=content,
            content_type=content_type,
            timeout=timeout,
        )

    def _stage(self, payload: dict) -> HttpResponse:
        task_id = uuid4().hex
        # 与远端使用相同的规范化摘要；不把认证头或 Token 写入发件箱。
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        record = {
            "endpoint": self._endpoint,
            "payload": json.loads(canonical),
            "request_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
            "state": "pending",
            "attempted": False,
            "cancel_requested": False,
        }
        self._save(task_id, record)
        body = (
            {"render_id": task_id, "status_uri": self._route + "/" + task_id}
            if self._mode == "ref2va"
            else {"job_token": task_id, "queue_position": 0}
        )
        return _response(202, body)

    def _observe(self, task_id: str, record: dict) -> HttpResponse:
        if record["state"] in {"cancelled", "rejected"}:
            return self._terminal(record)
        if record["cancel_requested"]:
            self._remote_cancel(task_id, record)
        status = self._http.request("GET", self._url + "/" + task_id)
        if status.status == 200:
            self._accepted(task_id, record)
            return status
        if status.status != 404:
            return self._unavailable(status)
        if record["state"] == "accepted":
            return self._reject(
                task_id,
                record,
                "remote_task_missing",
                "远端 H3 任务已丢失；不会重新生成，请人工检查节点。",
            )
        record["attempted"] = True
        self._save(task_id, record)
        # 原请求与同一标识重放；远端原子去重，不能用新标识绕过不确定的提交。
        result = self._http.request(
            "POST",
            self._url,
            json_body={**record["payload"], "submission_id": task_id},
            timeout=UPLOAD_TIMEOUT,
        )
        if result.status != 202:
            if result.status in {400, 401, 403, 404, 409, 413, 415, 422}:
                return self._reject(
                    task_id,
                    record,
                    "submission_rejected",
                    "H3 节点拒绝幂等提交，请检查节点版本、认证与请求参数。",
                )
            return self._unavailable(result)
        body = result.json_object()
        if body.get("render_id" if self._mode == "ref2va" else "job_token") != task_id:
            raise ModelProviderError("invalid_response", "H3 幂等提交回执的任务标识不匹配。")
        self._accepted(task_id, record)
        return self._http.request("GET", self._url + "/" + task_id)

    def _cancel(self, task_id: str, record: dict) -> HttpResponse:
        if record["state"] in {"cancelled", "rejected"}:
            return _response(202, {})
        record["cancel_requested"] = True
        self._save(task_id, record)
        if not record["attempted"] and record["state"] == "pending":
            record.update(state="cancelled", payload=None)
            self._save(task_id, record)
        else:
            self._remote_cancel(task_id, record)
        return _response(202, {})

    def _remote_cancel(self, task_id: str, record: dict) -> None:
        result = self._http.request(
            "DELETE",
            self._endpoint + "/minimax-h3/submissions/" + task_id,
            json_body={"kind": "h3_" + self._mode, "request_sha256": record["request_sha256"]},
        )
        if result.status != 202:
            raise ModelProviderError(
                "transport_error", "尚未确认 H3 取消；保留原句柄继续确认。", retryable=True
            )
        self._accepted(task_id, record)

    def _accepted(self, task_id: str, record: dict) -> None:
        if record["state"] != "accepted":
            record.update(state="accepted", payload=None)
            self._save(task_id, record)

    def _reject(self, task_id: str, record: dict, code: str, message: str) -> HttpResponse:
        record.update(state="rejected", payload=None, error=code, message=message)
        self._save(task_id, record)
        return self._terminal(record)

    def _terminal(self, record: dict) -> HttpResponse:
        cancelled = record["state"] == "cancelled"
        message = "H3 任务已在上传前取消。" if cancelled else record["message"]
        if self._mode == "ref2va":
            body = {
                "status": "cancelled" if cancelled else "failed",
                "progress_0_100": 0,
                "message": message,
            }
            if not cancelled:
                body["error"] = record["error"]
        else:
            body = {
                "stage": "stopped" if cancelled else "error",
                "ratio": 0,
                "description": message,
            }
            if not cancelled:
                body["error_tag"] = record["error"]
        return _response(200, body)

    @staticmethod
    def _unavailable(response: HttpResponse) -> HttpResponse:
        raise ModelProviderError(
            "transport_error",
            f"H3 节点暂不可用（HTTP {response.status}）；保留原提交等待恢复。",
            retryable=True,
        )

    def _path(self, task_id: str) -> Path:
        return self._directory / (task_id + ".json")

    def _save(self, task_id: str, record: dict) -> None:
        self._directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self._directory, delete=False
            ) as output:
                temporary = Path(output.name)
                json.dump(record, output, ensure_ascii=False, separators=(",", ":"))
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, self._path(task_id))
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


def _response(status: int, body: dict) -> HttpResponse:
    return HttpResponse(status, {}, json.dumps(body).encode("utf-8"))

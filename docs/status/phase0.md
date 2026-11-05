# Phase 0 — Environment Provisioning Status

- **Ngày tạo:** 2026-11-05
- **Branch:** `setup/environment-provisioning`
- **HEAD tại thời điểm tạo:** `2d663f7`
- **Phạm vi:** Phase 0 core-only (Option D). Chưa chạy full stack.
- **Trạng thái:** Step 7 (implementation, EP-01 → EP-15) hoàn tất. **Chưa chạy Step 8.**

> Gate: dừng sau EP-15 để chờ duyệt trước Step 8 (`EP-16 → EP-17`).

## 1. Mốc commit

| Commit | Nội dung |
|---|---|
| `292473d` | `chore(security)`: ignore local secret and key files |
| `91c703d` | `docs(design)`: amend TDDoc sau red-team review + topology correction |
| `144fa5e` | `docs(backlog)`: backlog environment provisioning, traceability 22 check |
| `51a2b1d` | Bootstrap `scripts/.venv` (CPython 3.12.15) + wrapper + interpreter guard |
| `c5666b4` | Loader `.env`, sanitizer, `safe_url` |
| `2dd3228` | Registry + exit-code semantics |
| `b10f8b4` | CLI, profiles, reporting |
| `f8ee635` | Budget 180s, semaphore 4, thứ tự deterministic |
| `186ebda` | Config/secret checks |
| `b47bd8a` | `config_precedence` + Docker checks |
| `ff3d9d2` | Disk, git identity, secret-hygiene checks |
| `76fc50b` | Ollama warm-up + 3 checks |
| `f092597` | 3 network checks có retry |
| `d3eaecf` | Output formatters (human/JSON) + `exit_phase` |
| `adf3d96` | Mở rộng unit coverage |
| `1de6c4b` | Integration coverage |
| `2d663f7` | E2E opt-in (3 test) |
| _(commit này)_ | `docs(status)`: ghi nhận trạng thái Phase 0 |

## 2. Deliverables Step 7

| EP | Nội dung | Commit | Trạng thái |
|---|---|---|---|
| EP-01/EP-02 | Venv 3.12.15, wrapper, interpreter guard | `51a2b1d` | ✅ |
| EP-03a/EP-03b | `.env` loader, sanitizer, `safe_url` | `c5666b4` | ✅ |
| EP-04 | Registry, exit code, CLI, profiles, reporting | `2dd3228`, `b10f8b4` | ✅ (gate đã duyệt) |
| EP-11 | Budget, semaphore, order | `f8ee635` | ✅ |
| EP-05 | Config/secret checks (1–5, 6, 7) | `186ebda` | ✅ |
| EP-06 | `config_precedence` + Docker checks (8–11) | `b47bd8a` | ✅ |
| EP-07 | Disk/git/hygiene checks (12–16) | `ff3d9d2` | ✅ |
| EP-08 | Ollama warm-up + checks 17–19 | `76fc50b` | ✅ |
| EP-09 | Network checks 20–22 | `f092597` | ✅ |
| EP-10 | Human/JSON output + `exit_phase` | `d3eaecf` | ✅ |
| EP-12 | Unit coverage mở rộng | `adf3d96` | ✅ |
| EP-13 | Integration tests | `1de6c4b` | ✅ |
| EP-14 | E2E opt-in (3 test) | `2d663f7` | ✅ |
| EP-15 | Status doc | commit này | ✅ |

## 3. Registry — 22 check theo thứ tự

1. `tooling_python`
2. `host_python_info`
3. `env_file`
4. `env_required_keys`
5. `durable_secrets`
6. `trading_safety_flags`
7. `llm_config`
8. `config_precedence`
9. `docker_compose_plugin`
10. `docker_compose_config`
11. `docker_daemon`
12. `disk_free`
13. `docker_disk_pressure`
14. `git_identity`
15. `git_identity_temporary` (ẩn ở `phase0` trừ `--verbose`)
16. `env_gitignored`
17. `ollama_service`
18. `ollama_model`
19. `ollama_smoke`
20. `binance_testnet`
21. `jupiter_lite`
22. `dexscreener`

## 4. Test status

```text
scripts/.venv/bin/python -m pytest scripts/tests -q
241 passed, 3 skipped
```

- 3 test E2E mặc định skip; chạy thủ công ở Step 8:
  `PREFLIGHT_E2E=1 scripts/.venv/bin/python -m pytest scripts/tests/test_e2e.py -q`
- Unit/integration không chạm mạng thật (dùng `httpx.MockTransport`); E2E là ngoại lệ có kiểm soát.
- Fixture chỉ dùng giá trị giả `FAKE_*`; không đọc/ghi secret thật.
- Integration có chạy `git config` / `git check-ignore` thật nhưng chỉ read-only trên repo.

## 5. Preflight dry-run — quan sát ngày 2026-11-05

Chạy `scripts/preflight --profile phase0` (chưa phải báo cáo Step 8 chính thức):

| Kết quả | Số lượng |
|---|---|
| PASS | 18 |
| WARN | 1 |
| FAIL critical | 2 |
| UNVERIFIED | 0 |
| Exit code | **1** |

Check FAIL:

- `env_required_keys`: `CUSTOM_API_URL`, `CUSTOM_MODEL` đang rỗng trong `.env`.
- `llm_config`: `LLM_PROVIDER` không phải `custom`; `CUSTOM_API_URL` không phải URL hợp lệ; `CUSTOM_MODEL` không phải `qwen2.5:1.5b`.

Check WARN (không đóng góp exit code):

- `config_precedence`: shell override trên `DB_POOL_MAX` / `DB_POOL_MIN` (interpolated); không phải safety key.

**Nguyên nhân:** `.env` hiện chưa được cấu hình cho Ollama cục bộ. Theo ràng buộc của phiên làm việc, `.env` **không bị sửa** trong Step 7.

**Hệ quả:** tiêu chí Step 8 “exit 0, không critical FAIL/UNVERIFIED” **chưa đạt** với trạng thái `.env` hiện tại. Cần owner quyết định trước Step 8, ví dụ cấu hình các key không-secret sau trong `.env`:

```dotenv
LLM_PROVIDER=custom
CUSTOM_API_URL=http://127.0.0.1:11434/v1
CUSTOM_MODEL=qwen2.5:1.5b
CUSTOM_API_KEY=
```

Không có giá trị secret nào được ghi vào tài liệu này.

## 6. Trạng thái trung gian đã biết

- Giữa EP-04 và EP-09, `scripts/preflight` trả exit `2` với thông báo
  `check registry is empty for profile 'phase0'`. Đây là trạng thái trung gian hợp lệ
  trong lúc registry chưa được nạp đủ 22 check, không phải lỗi.

## 7. Bước tiếp theo

1. Owner xử lý blocker `.env` ở mục 5 (hoặc chấp thuận một cách tiếp cận khác).
2. Step 8 = `EP-16` (chạy preflight, lưu human + JSON report) → `EP-17` (closeout).
3. Sau closeout, chờ duyệt sang Phase 1.

Các việc Phase 1 đã biết (chưa làm):

- Tạo GitHub fork và đặt identity thật; rewrite author các commit Phase 0.
- Chốt mô hình networking Ollama ↔ Docker trong Phase 1 TDDoc.
- Rebuild tài liệu tham chiếu Kronos từ đầu cho Phase 2.

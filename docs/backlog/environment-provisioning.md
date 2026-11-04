# Backlog — Environment Provisioning (Phase 0)

- **Ngày:** 2026-11-04
- **Trạng thái:** Approved (Step 6) — 3 điều chỉnh owner đã áp dụng: commit ngay, tách EP-03a/EP-03b, thêm budget-exhaustion test cho EP-11
- **TDDoc:** `docs/design/2026-11-04-environment-provisioning.md`
- **Red-team review + Resolution:** `docs/reviews/2026-11-04-environment-provisioning-review.md`
- **Branch:** `setup/environment-provisioning`
- **Base commit:** `dd90b83`
- **Commit mốc:**
  - `292473d` — `chore(security): ignore local secret and key files` (security baseline)
  - `91c703d` — `docs(design): amend environment provisioning TDDoc after red-team review and topology correction` (design baseline)
- **Số check Phase 0:** **22**
- **Điều kiện Phase 0 done:** `scripts/preflight --profile phase0` trả **exit 0**, không có critical `FAIL`, không có `UNVERIFIED`.

---

## 1. Mục tiêu Step 7

Triển khai preflight tool đúng TDDoc đã duyệt:

1. Tạo venv tooling Python 3.12.15 tại `scripts/.venv/`.
2. Tạo wrapper `scripts/preflight` + `scripts/preflight_check.py`.
3. Implement đủ **22 check**, bootstrap, sanitizer, output human/JSON, exit code 0/1/2.
4. Viết unit + integration + E2E test; đạt 100% branch coverage cho sanitizer/exit code/timeout.
5. Không sửa `.env`, `docker-compose.yml`, Ollama config; không cài package ngoài 4 dependency đã chốt.

---

## 2. Ràng buộc bắt buộc

| Ràng buộc | Chi tiết |
|---|---|
| Không sửa `.env` | Chỉ đọc; không chmod, không backup, không xoay secret |
| Không sửa `docker-compose.yml` | `config_precedence` chỉ đọc compose-resolved config |
| Không đổi Ollama | Giữ `127.0.0.1:11434`; chỉ gọi API |
| Không cài host package | Chỉ 4 gói trong `scripts/.venv`: `httpx`, `python-dotenv`, `pytest`, `pytest-asyncio` |
| Không dùng host Python 3.14 | Wrapper bắt buộc dùng `scripts/.venv/bin/python` |
| Không dùng `requests`/`respx` | Dùng `httpx` + `httpx.MockTransport` |
| Không log secret | Chỉ tên key, độ dài, trạng thái; sanitizer toàn cục |
| Không mở rộng scope | Không Axiom/MT5/TradingView/Helius/OKX/Kronos/Tauric ở Phase 0 |

---

## 3. Task breakdown

**18 task items** (EP-01…EP-17 + tách EP-03a/EP-03b; ID giữ nguyên để khớp commit milestones, EP-05…EP-17 không đánh số lại).

| ID | Task | Ưu tiên | Phụ thuộc | Ước lượng | Acceptance |
|---|---|---|---|---|---|
| **EP-01** | Tạo venv tooling + cài 4 dependency | P0 | — | S | `scripts/.venv/bin/python` là CPython 3.12.x; import được `httpx`, `dotenv`, `pytest`; không cài gì lên host |
| **EP-02** | Wrapper `scripts/preflight` + interpreter guard | P0 | EP-01 | S | Thiếu venv → exit 2 kèm hướng dẫn; sai Python/venv → exit 2, không traceback; đúng → forward args |
| **EP-03a** | Loader `.env` + sanitizer | P0 | EP-02 | M | Không mutate `os.environ`; parser lỗi → exit 2; canary không xuất hiện ở stdout/stderr/JSON |
| **EP-03b** | `safe_url()` redaction | P0 | EP-03a | S | Bỏ userinfo/query/fragment; áp dụng cho mọi output/HTTP detail; không lộ credential |
| **EP-04** | Registry, profile, CLI, exit-code runner | P0 | EP-02, EP-03a, EP-03b | M | `--profile` mặc định `phase0`; `--list-checks`; `--json`; `--no-color`; `--verbose`; profile lạ → exit 2 |
| **EP-05** | Local checks nhóm config/secret (7 check) | P0 | EP-03a, EP-03b, EP-04 | L | `tooling_python`, `host_python_info`, `env_file`, `env_required_keys`, `durable_secrets`, `trading_safety_flags`, `llm_config` pass/fail đúng TDDoc |
| **EP-06** | Config precedence + Docker checks (4 check) | P0 | EP-04 | L | `config_precedence` 3 bước; `docker_compose_plugin`/`docker_compose_config` → exit 2 khi lỗi; `docker_daemon` → exit 1 |
| **EP-07** | Disk, git, secret-hygiene checks (5 check) | P0 | EP-04 | M | `disk_free` ≥20 GiB; `docker_disk_pressure` warning; `git_identity`; `git_identity_temporary` suppress phase0; `env_gitignored` 7 paths |
| **EP-08** | Ollama warm-up + 3 check | P0 | EP-04 | M | Warm-up 30s fail → exit 2; `ollama_service`/`ollama_model`/`ollama_smoke`; smoke 15s, no retry, critical |
| **EP-09** | Network checks ngoài (3 check) | P0 | EP-04 | M | Binance 8s + 2 retry; Jupiter/DexScreener 5s + 2 retry; 429 sau retry → FAIL critical; timeout → FAIL |
| **EP-10** | Output formatters (human + JSON) | P0 | EP-04 | M | Bảng `[PASS/FAIL/WARN/SKIP/UNVERIFIED]`; màu đúng; JSON có `environment.tooling_python`, `severity`, `summary`, `exit_code`; không có value secret |
| **EP-11** | Budget, semaphore, deterministic order | P0 | EP-04, EP-09 | S | Budget 180s; semaphore 4; Ollama group tuần tự; thứ tự output theo registry; cạn budget critical → UNVERIFIED → exit 1; **integration test budget-exhaustion** (22 check chậm, vượt 180s → exit 1, message "budget exhausted before critical check X", không treo) |
| **EP-12** | Unit tests (~50) | P0 | EP-05…EP-11 | L | 100% pass; 100% branch cho sanitizer/exit code/timeout; không chạm mạng thật |
| **EP-13** | Integration tests (~14) | P0 | EP-12 | M | `httpx.MockTransport`; `.env` fixture; compose JSON fixture; schema JSON; deterministic order |
| **EP-14** | E2E tests (3) | P1 | EP-13 | S | Đánh dấu `@pytest.mark.e2e`, mặc định skip; chạy thủ công Step 8 |
| **EP-15** | Tạo `docs/status/phase0.md` | P1 | EP-14 | S | Ghi commit mốc `292473d`, `91c703d`; điền kết quả preflight sau Step 8 |
| **EP-16** | Chạy preflight Step 8 + lưu báo cáo | P0 | EP-12…EP-15 | S | Human + JSON report; exit 0; không critical FAIL/UNVERIFIED; lưu bằng chứng |
| **EP-17** | Phase 0 closeout | P0 | EP-16 | S | Repo sạch; `.env` không đổi; flags `false`; commit cuối; cập nhật status |

**Ước lượng:** S ≤ 1 giờ, M 1–3 giờ, L 3–6 giờ. Tổng dự kiến 1,5–2 ngày làm việc tập trung.

---

## 4. Chi tiết acceptance theo task

### EP-01 — Venv tooling

- Tạo `scripts/.venv` bằng CPython 3.12.15 có sẵn của `uv`.
- Cài đúng 4 gói: `httpx`, `python-dotenv`, `pytest`, `pytest-asyncio`.
- Không tạo `requirements.txt` mới trừ khi cần pin; nếu tạo, đặt trong `scripts/` và ghi rõ.
- Kiểm chứng: `scripts/.venv/bin/python -c "import sys, httpx, dotenv; print(sys.version)"` → `3.12.x`.
- `scripts/.venv/` đã bị `.gitignore` che bởi `.venv/`; không sửa `.gitignore`.

### EP-02 — Wrapper + interpreter guard

- `scripts/preflight` là shell script, có thể chạy từ bất kỳ cwd nào; tự resolve repo root.
- Nếu `scripts/.venv/bin/python` không tồn tại → in hướng dẫn `uv venv ...`, exit 2.
- `scripts/preflight_check.py` kiểm tra `sys.version_info` là 3.12.x và `sys.prefix` trỏ `scripts/.venv`; sai → exit 2, không traceback.
- Không import `httpx`/`dotenv` trước guard.

### EP-03a — Loader + sanitizer

- `python-dotenv` đọc mapping; **không** `load_dotenv()` mutate `os.environ`.
- Sanitizer cài trước khi đọc; fallback pattern cho parser lỗi.
- Suppress toàn bộ warning/exception dotenv; lỗi parser chỉ chứa path + line + loại lỗi.
- Redaction exact-match ≥8 ký tự; mask theo key.
- Test canary bắt buộc trước khi merge.

### EP-03b — `safe_url()`

- `safe_url()` bỏ userinfo (`user:pass@`), query, fragment; chỉ giữ scheme + host + port + path.
- Áp dụng cho mọi check có HTTP call hoặc so sánh URL (`llm_config`, `config_precedence`, output detail).
- Không log/không trả về credential dù URL đầu vào có token.
- Unit test riêng cho: URL có userinfo, query token, fragment, port, IPv4; URL rỗng/không hợp lệ.

### EP-04 — Registry/CLI

- Profile mặc định `phase0`; `--profile phaseN`; profile lạ → exit 2.
- `--list-checks` in ID, severity, timeout.
- `--json` chỉ in JSON ra stdout; log ra stderr.
- `--no-color`/`NO_COLOR`/non-TTY tắt màu.
- `--verbose` bật traceback đã sanitize + key thiếu từ `.env.example`.
- `--offline`/`--tag network`: **không implement**, chỉ chừa interface/placeholder; không được làm hỏng CLI.

### EP-05 — Config/secret checks

- `tooling_python` pass 3.12.x; fail → exit 2.
- `host_python_info` informational, không đóng góp exit code.
- `env_file`: resolve symlink, `mode & 0o077 == 0`, owner hiện tại.
- `env_required_keys`: đủ 8 key; `CUSTOM_API_KEY` được rỗng.
- `durable_secrets`: độ dài + blacklist; không in giá trị.
- `trading_safety_flags`: allowlist `{false,0,no,off}`; mọi giá trị khác → FAIL critical.
- `llm_config`: provider custom; host/port/path/model đúng; key rỗng.

### EP-06 — Config precedence + Docker

- Parse `docker compose config --format json` in-memory.
- Bước 1: `backend` + ≥1 worker mount `./.env:/app/.env` → nếu thiếu FAIL critical.
- Bước 2: 8 key an toàn không có trong `environment:` của bất kỳ service → nếu có FAIL critical, nêu tên service + key.
- Bước 3: key interpolated lệch `.env` → WARN, nêu tên key + hậu quả auth; không exit code.
- `docker_compose_plugin` fail → exit 2.
- `docker_compose_config` fail → exit 2; stderr redacted.
- `docker_daemon` fail → exit 1.

### EP-07 — Disk/git/secret hygiene

- `disk_free` ≥20 GiB cho repo + Docker root; nếu khác filesystem, báo cả hai.
- `docker_disk_pressure`: `docker system df`; >80% hoặc lỗi → WARN; không exit code.
- `git_identity`: local `user.name`/`user.email` non-empty.
- `git_identity_temporary`: WARN nếu `@localhost` hoặc `haosanh-agent`; phase0 chỉ hiện khi `--verbose`.
- `env_gitignored`: 7 paths `.env`, `backend_api_python/.env`, `.keys/`, `secrets/`, `*.pem`, `*.key`, `*.gpg`; tất cả ignored và không tracked; sai → FAIL critical.

### EP-08 — Ollama

- Warm-up trước registry: `/api/generate` prompt ngắn, budget 30s; fail → exit 2.
- `ollama_service`: `GET /api/version` 200 + version.
- `ollama_model`: `/api/tags` chứa đúng `qwen2.5:1.5b`.
- `ollama_smoke`: `POST /api/generate` `num_predict=1`, `stream=false`; 15s; no retry; critical; không log body.

### EP-09 — Network ngoài

- Binance: `GET https://testnet.binance.vision/api/v3/ping`; 8s/attempt; 2 retry; 200 `{}`.
- Jupiter: `GET https://lite-api.jup.ag/price/v3?ids=...`; 5s; 2 retry; 200 + key mint.
- DexScreener: `GET https://api.dexscreener.com/latest/dex/search?q=SOL`; 5s; 2 retry; 200 + `pairs`.
- Retry chỉ timeout/conn/5xx/429; backoff 0.5s → 1.5s + jitter; 429 sau retry → FAIL critical.
- Không gửi API key, không đặt lệnh.

### EP-10 — Output

- Human: `[STATUS] | Check ID | Detail | Duration`.
- Màu: xanh PASS, đỏ FAIL critical, vàng WARN/SKIP/UNVERIFIED.
- JSON schema_version 1; `environment.tooling_python` + `host_python`; mỗi check có `severity`; summary đầy đủ; `exit_code`.
- Không có trường/value secret.

### EP-11 — Budget/ordering

- Budget 180s sau bootstrap.
- Semaphore 4; Ollama group tuần tự.
- Output theo registry, không theo thứ tự hoàn thành.
- Cạn budget critical → UNVERIFIED → exit 1; warning → SKIP.
- **Bắt buộc integration test budget exhaustion:** registry giả 22 check đều chậm (tổng > 180s), budget ngắn (inject clock/budget để test nhanh) → preflight exit 1, detail chứa `budget exhausted before critical check <id>`, tiến trình kết thúc trong thời gian hữu hạn (không treo, không chờ hết 22 check).
- Test phải chứng minh: check critical chưa chạy → `UNVERIFIED`, check warning chưa chạy → `SKIP`, và không có `FAIL` giả do budget.

### EP-12–EP-14 — Tests

- Unit ~50; integration ~14; E2E 3.
- 100% pass; không chạm mạng thật ngoài E2E.
- 100% branch coverage: sanitizer, exit-code classification, timeout/retry.
- Coverage module check ≥90%.
- E2E `@pytest.mark.e2e`, skip mặc định.

### EP-15 — Status doc

- Tạo `docs/status/phase0.md`.
- Ghi commit mốc: `292473d` (security), `91c703d` (design).
- Điền kết quả Step 8: ngày chạy, exit code, số PASS/WARN/FAIL/UNVERIFIED, đường dẫn report.
- Không ghi secret.

### EP-16 — Chạy preflight

- `scripts/preflight --profile phase0` → exit 0.
- `scripts/preflight --profile phase0 --json > /tmp/preflight-phase0.json`.
- Lưu báo cáo vào `docs/status/` hoặc `artifacts/` (chỉ text/JSON, không secret).
- Xác nhận không critical FAIL/UNVERIFIED.

### EP-17 — Closeout

- `git status` sạch; không thay đổi `.env`/`docker-compose.yml`.
- `LIVE_TRADING_ENABLED=false`, `JEV_ENABLED=false` vẫn đúng (chỉ kiểm tra boolean, không in giá trị).
- Commit cuối + cập nhật backlog trạng thái Done.

---

## 5. Traceability — 22 check → task → test

| # | Check | Task | Test chính |
|---|---|---|---|
| 1 | `tooling_python` | EP-05 | UT-05-01, E2E-02 |
| 2 | `host_python_info` | EP-05 | UT-05-02 |
| 3 | `env_file` | EP-05 | UT-05-03 |
| 4 | `env_required_keys` | EP-05 | UT-05-04, IT-03 |
| 5 | `durable_secrets` | EP-05 | UT-05-05 |
| 6 | `trading_safety_flags` | EP-05 | UT-05-06 |
| 7 | `llm_config` | EP-05 | UT-05-07 |
| 8 | `config_precedence` | EP-06 | UT-06-01, IT-08 |
| 9 | `docker_compose_plugin` | EP-06 | UT-06-02 |
| 10 | `docker_compose_config` | EP-06 | UT-06-03, IT-09 |
| 11 | `docker_daemon` | EP-06 | UT-06-04 |
| 12 | `disk_free` | EP-07 | UT-07-01 |
| 13 | `docker_disk_pressure` | EP-07 | UT-07-02 |
| 14 | `git_identity` | EP-07 | UT-07-03, IT-10 |
| 15 | `git_identity_temporary` | EP-07 | UT-07-04 |
| 16 | `env_gitignored` | EP-07 | UT-07-05, IT-11 |
| 17 | `ollama_service` | EP-08 | UT-08-01, IT-12 |
| 18 | `ollama_model` | EP-08 | UT-08-02 |
| 19 | `ollama_smoke` | EP-08 | UT-08-03 |
| 20 | `binance_testnet` | EP-09 | UT-09-01, IT-13 |
| 21 | `jupiter_lite` | EP-09 | UT-09-02 |
| 22 | `dexscreener` | EP-09 | UT-09-03 |

---

## 6. Deferred — không làm ở Phase 0

| ID | Hạng mục | Phase | Ghi chú |
|---|---|---|---|
| DF-01 | Ollama ↔ Docker networking | Phase 1 | Chốt A/B/C trong TDDoc Phase 1 |
| DF-02 | GPU allocation Kronos vs LLM 7B | Phase 2/3 | GTX 1650 4,2GB VRAM |
| DF-03 | Reset author commit Phase 0 trước khi push | Phase 1 | Identity tạm hiện tại |
| DF-04 | Profile `phase1` với disk ≥30 GiB | Phase 1 | Chưa implement |
| DF-05 | `--offline` / `--tag network` cho CI | Phase 1+ | Design only ở Phase 0 |
| DF-06 | Chuyển secret ra khỏi cùng ổ đĩa | Phase 10 | P0 blocker |
| DF-07 | Inject 8 key vào compose `environment:` | Phase 1+ | Chỉ nếu topology thay đổi |
| DF-08 | Rebuild Kronos reference | Phase 2 | Bản Trash đã bị xóa vĩnh viễn |
| DF-09 | `docker system df` chi tiết hơn (theo image/volume) | Phase 1 | Hiện chỉ warning |

---

## 7. Thứ tự thực thi Step 7

Thứ tự nghiêm ngặt (owner-approved): không implement check nào trước khi EP-04 xong; không chạy 22 check cùng nhau trước khi EP-11 xong.

```
EP-01 → EP-02 → EP-03a → EP-03b → EP-04 🔒 → EP-11
  → EP-05 → EP-06 → EP-07 → EP-08 → EP-09
  → EP-10 → EP-12 → EP-13 → EP-14 → EP-15
```

- 🔒 **EP-04** là cổng chặn duy nhất trong giai đoạn implement: dừng, báo cáo, chờ duyệt.
- 🔒 Sau **EP-15** (closeout) dừng trước Step 8.
- Các nhóm khác: báo cáo rồi tiếp tục, không cần chờ duyệt từng commit.

Step 8: `EP-16 → EP-17`.

---

## 8. Commit milestones

| Mốc | Commit | Nội dung |
|---|---|---|
| Base | `dd90b83` | QuantDinger v5 base |
| Security | `292473d` | `.gitignore` hardening |
| Design | `91c703d` | TDDoc + review resolved |
| Backlog | _commit này_ | Backlog approved (18 task, 22-check traceability) |
| Implementation | _chưa có_ | Step 7 |
| Verification | _chưa có_ | Step 8 |

---

## 9. Rủi ro thi công

| Rủi ro | Giảm thiểu |
|---|---|
| `httpx.MockTransport` không mô phỏng đúng timeout | Dùng handler async ngủ; test với timeout 0,1s |
| Compose JSON thay đổi cấu trúc giữa phiên bản | Fixture + test parse thực tế; fail rõ nếu schema lạ |
| Ollama warm-up fail do service chưa bật | Hướng dẫn `systemctl --user status ollama`; exit 2 |
| Test canary vô tình dùng secret thật | Fixture tổng hợp, không đọc `.env` thật |
| Venv bị commit nhầm | `.venv/` đã ignore; kiểm tra `git status` trước commit |
| Sửa nhầm `.env`/compose | Chỉ đọc; review diff trước commit |

---

## 10. Checklist duyệt Step 6

- [ ] 22 check đều có task tương ứng.
- [ ] Không task nào mở rộng sang Phase 1+.
- [ ] Deferred list đầy đủ.
- [ ] Acceptance criteria rõ ràng, kiểm chứng được.
- [ ] Không có secret trong backlog.
- [ ] Thứ tự thực thi Step 7 hợp lý.

---

**Duyệt Step 6 xong → Step 7 được phép bắt đầu.**

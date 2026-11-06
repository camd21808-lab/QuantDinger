# Phase 0 — Environment Provisioning Status

- **Ngày tạo:** 2026-11-05
- **Branch:** `setup/environment-provisioning`
- **HEAD tại thời điểm tạo:** `2d663f7`
- **Phạm vi:** Phase 0 core-only (Option D). Chưa chạy full stack.
- **Trạng thái:** Phase 0 closeout hoàn tất (EP-01 → EP-17).

> Gate: Phase 0 đã đóng; chờ owner duyệt sang Phase 1.

> **Lưu ý hash:** các hash trong tài liệu này là hash **trước** đợt rewrite author ngày 2026-11-06. Bảng đối chiếu đầy đủ ở §9.1.

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
| `2820cd0` | `docs(status)`: ghi nhận trạng thái Phase 0 |
| `2810cc8` | `docs(status)`: ghi nhận thay đổi LLM config được duyệt |
| `550ce4f` | `docs(status)`: ghi nhận kết quả preflight Phase 0 |
| _(commit này)_ | `docs(status)`: closeout Phase 0 |

## 2. Deliverables (EP-01 → EP-17)

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
| EP-15 | Status doc | `2820cd0` | ✅ |
| EP-16 | Chạy preflight + lưu báo cáo | `550ce4f` | ✅ |
| EP-17 | Closeout Phase 0 | commit này | ✅ |

## 2a. LLM config change — 2026-11-05 21:18 (+07)

- **Pre-change:** `LLM_PROVIDER=openrouter` (không dùng; các key `CUSTOM_*` rỗng).
- **Post-change:** `LLM_PROVIDER=custom`, `CUSTOM_API_URL=http://127.0.0.1:11434/v1`,
  `CUSTOM_MODEL=qwen2.5:1.5b`, `CUSTOM_API_KEY=` (rỗng).
- **Lý do:** chuyển sang Ollama cục bộ theo kế hoạch Phase 0.
- **Backup:** `/home/rew/backups/haosanh/env-pre-llm-config-20261105-211848.gpg`
  (GPG AES256, mode 600, owner `rew:rew`; giải mã diff khớp byte-for-byte trước khi sửa).
- **Diff:** đúng 3 dòng nội dung thay đổi (`LLM_PROVIDER`, `CUSTOM_API_URL`,
  `CUSTOM_MODEL`). `CUSTOM_API_KEY` đã tồn tại và giữ nguyên rỗng nên không đổi byte.
  Không có dòng nào khác thay đổi; không thêm/xóa key, không đổi thứ tự/comment.
- **Permission:** `600 rew:rew` (không đổi).
- **Verified:** `docker compose config --quiet` → OK; Ollama
  `POST /v1/chat/completions` → HTTP 200, `choices` có mặt.
- Không ghi giá trị secret hay passphrase.

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

## 5. Preflight — Step 8 (EP-16), 2026-11-05

Lệnh đã chạy:

```bash
scripts/preflight --profile phase0
scripts/preflight --profile phase0 --json
```

Bằng chứng đã lưu:

- `docs/status/artifacts/preflight-phase0-2026-11-05.txt`
- `docs/status/artifacts/preflight-phase0-2026-11-05.json`

| Kết quả | Số lượng |
|---|---|
| PASS | 20 |
| WARN | 1 |
| FAIL critical | 0 |
| UNVERIFIED | 0 |
| Exit code | **0** |

- `phase0` mặc định hiển thị 21 check; `git_identity_temporary` bị ẩn theo thiết kế
  (chỉ hiện với `--verbose`). Registry vẫn đủ **22 check**.
- WARN duy nhất: `config_precedence` báo shell override trên `DB_POOL_MAX` / `DB_POOL_MIN`
  (interpolated). Đây không phải safety key và **không** đóng góp exit code.
- JSON đã kiểm tra: `schema_version=1`, `exit_phase=run`, `exit_code=0`,
  không có trường `value`, không có critical FAIL/UNVERIFIED.
- Trước thay đổi ở mục 2a, dry-run từng trả exit 1 với 2 critical FAIL
  (`env_required_keys`, `llm_config`). Sau khi cấu hình đúng 4 key được duyệt,
  cả hai check đều PASS.
- Không có giá trị secret nào trong báo cáo human/JSON hay tài liệu này.

## 6. Trạng thái trung gian đã biết

- Giữa EP-04 và EP-09, `scripts/preflight` trả exit `2` với thông báo
  `check registry is empty for profile 'phase0'`. Đây là trạng thái trung gian hợp lệ
  trong lúc registry chưa được nạp đủ 22 check, không phải lỗi.

## 7. Closeout (EP-17) — 2026-11-05

- **Repo:** working tree sạch sau commit closeout.
- **`.env`:** không bị git track (đã nằm trong `.gitignore`); mode `600`, owner `rew:rew`.
- **Safety flags:** `LIVE_TRADING_ENABLED=false`, `JEV_ENABLED=false` (giữ nguyên).
- **Backup `.env`:** `/home/rew/backups/haosanh/env-pre-llm-config-20261105-211848.gpg`,
  mode `600`, owner `rew:rew`.
- **Test cuối:** `241 passed, 3 skipped`.
- **Preflight cuối:** exit `0`, 20 PASS / 1 WARN / 0 FAIL / 0 UNVERIFIED.
- **Commit EP-16:** `550ce4f`; **commit closeout:** commit này.
- Không có giá trị secret nào được ghi lại.

## 8. Bước tiếp theo

Phase 0 đã hoàn tất; chờ owner duyệt sang Phase 1.

Các việc Phase 1 đã biết (chưa làm):

- Tạo GitHub fork và đặt identity thật; rewrite author các commit Phase 0.
- Chốt mô hình networking Ollama ↔ Docker trong Phase 1 TDDoc.
- Rebuild tài liệu tham chiếu Kronos từ đầu cho Phase 2.

## 9. Phase 1 pre-conditions — 2026-11-06

### 9.1 Git identity và rewrite lịch sử

- Identity chốt: `j pham <camd21808@gmail.com>` (`git config --local`).
- Phạm vi rewrite: **21 commit Phase 0**; 759 commit upstream giữ nguyên tác giả gốc.
- Lệnh: `git rebase upstream/main --exec 'git commit --amend --no-edit --author="j pham <camd21808@gmail.com>"'`.
- Verify:
  - 21/21 commit có author + committer `j pham <camd21808@gmail.com>`.
  - Tree hash trước/sau giống nhau: `7f958e7b0fd9d2bd6df9a3339874b7aeafcac3be`.
  - Không còn commit `haosanh-agent` trong range.
  - `upstream/main` không đổi: `dd90b83b0d2323efb3869049052dcdffeb2b6bde`; 41 tác giả gốc giữ nguyên.
- Backup trước rewrite (mode `600`, owner `rew:rew`):
  - `repo-pre-rewrite-20261105-214014.bundle` — 101 refs, `git bundle verify` OK.
  - `gitdir-pre-rewrite-20261105-214014.tar.gz`
  - `MANIFEST-20261105-214014.txt` — sha256 của cả hai.

Đối chiếu hash trước → sau rewrite:

| Trước | Sau | Nội dung |
|---|---|---|
| `815063c` | `e91194c` | `docs(status)`: close out phase 0 |
| `550ce4f` | `f986390` | `docs(status)`: record phase 0 preflight results |
| `2810cc8` | `0ea072c` | `docs(status)`: record approved llm config change |
| `2820cd0` | `3ec1114` | `docs(status)`: record phase 0 implementation status |
| `2d663f7` | `12f8f90` | `test(preflight)`: add opt-in e2e coverage |
| `1de6c4b` | `ab844e2` | `test(preflight)`: add integration coverage for the check pipeline |
| `adf3d96` | `e0da2aa` | `test(preflight)`: expand unit coverage for checks and runner |
| `d3eaecf` | `8fdb00f` | `feat(preflight)`: add output formatters and exit phase |
| `f092597` | `7abf340` | `feat(preflight)`: add retrying network checks |
| `76fc50b` | `a860370` | `feat(preflight)`: add ollama warm-up and checks |
| `ff3d9d2` | `abeacc6` | `feat(preflight)`: add disk, git and hygiene checks |
| `b47bd8a` | `be72c6f` | `feat(preflight)`: add precedence and docker checks |
| `186ebda` | `20687fa` | `feat(preflight)`: add config/secret checks |
| `f8ee635` | `3dd76b0` | `feat(preflight)`: add budget and concurrency control |
| `b10f8b4` | `1256b63` | `feat(preflight)`: add CLI, profiles and reporting |
| `2dd3228` | `e30ba4d` | `feat(preflight)`: add check registry and exit-code semantics |
| `c5666b4` | `c98f2dd` | `feat(preflight)`: add config loader, sanitizer, safe_url |
| `51a2b1d` | `36ab78c` | `chore(preflight)`: bootstrap venv and wrapper |
| `144fa5e` | `c3358d8` | `docs(backlog)`: add environment provisioning backlog with 22-check traceability |
| `91c703d` | `9b2989c` | `docs(design)`: amend environment provisioning TDDoc after red-team review and topology correction |
| `292473d` | `ad5eee2` | `chore(security)`: ignore local secret and key files |

### 9.2 Remotes

| Remote | URL |
|---|---|
| `origin` | `git@github.com:guang/QuantDinger.git` (fork) |
| `upstream` | `https://github.com/OpenByteInc/QuantDinger.git` |

`main` track `upstream/main`; `setup/environment-provisioning` chưa push.

### 9.3 SSH key

- `~/.ssh/id_ed25519_quantdinger` (ed25519, mode `600`) + entry `github.com` trong `~/.ssh/config`.
- Fingerprint: `SHA256:ewLay3zvdXSdAkoj4PTaSXf3E22jYU+C5laSSkOwvCg`.
- Trạng thái: **chưa thêm vào GitHub** → push đang blocked.

### 9.4 Ollama ↔ Docker — phương án B2 relay

- Ollama giữ nguyên `127.0.0.1:11434` (user unit `ollama.service`); `.env` không đổi.
- Cơ chế relay: **(c) `systemd-socket-proxyd`**, user-space, không cần sudo.
  - `~/.config/systemd/user/ollama-bridge.socket` — `ListenStream=172.17.0.1:11434`, `FreeBind=true`.
  - `~/.config/systemd/user/ollama-bridge.service` — `ExecStart=/usr/lib/systemd/systemd-socket-proxyd 127.0.0.1:11434`, `Restart=always`.
  - Bản sao versioned: `scripts/systemd/`.
- Persistent:
  - `systemctl --user is-enabled ollama-bridge.socket` → `enabled`.
  - `loginctl show-user rew -p Linger` → `yes` (user manager chạy từ boot, không cần login).
  - `FreeBind=true` xử lý boot-order; đã test bind thành công trên địa chỉ chưa tồn tại `172.31.255.254:11435`.
- Bề mặt mạng:
  - Chỉ `127.0.0.1:11434` và `172.17.0.1:11434` listen.
  - `192.168.2.77:11434` → `ConnectionRefused`.
  - Container trên default bridge và trên user-defined network (gateway `172.22.0.1`) đều gọi được `host.docker.internal:11434`.
- Restart test: `systemctl --user restart ollama-bridge.socket` → listener + container path vẫn OK.
- **Chưa chạy reboot thật** (sẽ ngắt phiên agent). Lệnh verify sau reboot:
  `ss -ltn | grep 11434 && systemctl --user is-active ollama-bridge.socket && scripts/preflight --profile phase0`

### 9.5 `docker-compose.override.yml`

- File mới, **đã nằm trong `.gitignore`** (dòng 114) nên không commit; `docker-compose.yml` gốc không sửa.
- Chỉ thêm `extra_hosts: ["host.docker.internal:host-gateway"]` cho 10 service:
  `backend`, `mcp`, `trading-worker`, `kafka-audit-worker`,
  `strategy-dispatcher-worker`, `strategy-evaluator-worker`, `scheduler-worker`,
  `celery-worker`, `celery-backtest-worker`, `celery-beat`.
- `docker compose config --quiet` → OK.
- Chưa đổi `CUSTOM_API_URL`. Trong container, giá trị `http://127.0.0.1:11434/v1` từ `.env`
  trỏ vào chính container → Phase 1 phải override thành `http://host.docker.internal:11434/v1`.

### 9.6 Preflight sau thay đổi

- `scripts/preflight --profile phase0` → exit `0`, 20 PASS / 1 WARN / 0 FAIL / 0 UNVERIFIED.
- WARN duy nhất vẫn là false-positive `config_precedence` cho `DB_POOL_MAX`/`DB_POOL_MIN`.

### 9.7 Còn mở

- Push fork: chờ SSH key được thêm vào GitHub.
- Disk cleanup: chờ duyệt từng mục (mục tiêu ≥35 GiB; hiện 27.46 GiB).

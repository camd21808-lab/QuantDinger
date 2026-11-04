# TDDoc — Environment Provisioning (Phase 0)

- **Ngày:** 2026-11-04
- **Trạng thái:** Amended after red-team review and topology correction — chờ duyệt (Step 6)
- **Phạm vi:** Phase 0 (core-only, Option D)
- **Repo:** `haosanh` (fork QuantDinger v5)
- **Base commit:** `dd90b83`
- **Commit mốc hiện tại:** `292473d` — `chore(security): ignore local secret and key files`
- **Liên quan:** `scripts/preflight_check.py`, `scripts/preflight` (sẽ tạo ở Step 7)
- **Amendment:** 2026-11-04 — sau red-team review + topology correction; xem `docs/reviews/2026-11-04-environment-provisioning-review.md`

---

## 1. Goals

Phase 0 thiết lập một môi trường phát triển **an toàn, tái lập được, không bật live trading**, đủ điều kiện để bước sang Phase 1 mà không phải sửa lại nền tảng.

Mục tiêu cụ thể:

1. **Xác nhận môi trường host** đủ điều kiện chạy các module Phase 0: Python tooling, Docker daemon, dung lượng đĩa, git identity.
2. **Xác nhận cấu hình bí mật an toàn**: `.env` tồn tại, quyền file đúng, ba secret bền vững (`SECRET_KEY`, `CREDENTIAL_ENCRYPTION_KEY`, `POSTGRES_PASSWORD`) không dùng giá trị mặc định.
3. **Xác nhận các cờ an toàn**: `LIVE_TRADING_ENABLED=false`, `JEV_ENABLED=false`.
4. **Xác nhận nguồn cấu hình runtime**: mô hình mounted `.env` hoạt động; 8 key an toàn không bị override qua `environment:` của Compose.
5. **Xác nhận LLM cục bộ hoạt động**: Ollama phản hồi, model `qwen2.5:1.5b` có mặt, sinh được token sau warm-up.
6. **Xác nhận kết nối mạng tối thiểu** cho Phase 0: Binance testnet, Jupiter Lite, DexScreener.
7. **Cung cấp một công cụ preflight tái sử dụng, profile-based**, trả về exit code rõ ràng, output human-readable + JSON, không bao giờ làm lộ secret.
8. **Tạo mốc kiểm chứng** để Step 8 chạy và báo cáo trước khi sang Phase 1.

Thành công của Phase 0 được đo bằng: `scripts/preflight --profile phase0` trả **exit code 0** trên máy này, với **không có critical FAIL và không có critical UNVERIFIED** (WARN/SKIP của warning được phép), và kết quả được lưu làm bằng chứng.

---

## 2. Non-goals

Phase 0 **không** làm những việc sau (để tránh mở rộng scope và tiêu tốn tài nguyên):

### 2.1. Thành phần thuộc phase sau
- **Axiom** — defer sang Phase 6/9.
- **MT5** — defer sang Phase 6/9.
- **TradingView MCP** — defer sang Phase 6/9.
- **Helius** — defer sang Phase 6/9.
- **OKX demo** — defer sang Phase 6/9.
- **Kronos service** (Phase 2), **Tauric** (Phase 3), **NexusTrader-mcp** (Phase 4+), exchange adapters mới — không cài, không cấu hình ở Phase 0.
- **Guardrail implementation** (JEV deterministic guardrail) — chỉ thiết kế trong TDDoc Phase 4; Phase 0 chỉ kiểm tra cờ `JEV_ENABLED=false`.

### 2.2. Hạ tầng / vận hành
- **Không chạy full stack** QuantDinger (Option D: phát triển/test từng module độc lập, không đồng thời).
- **Không** `docker compose up`, không build image QuantDinger ở Phase 0.
- **Không** cài CUDA toolkit, không đổi driver GPU, không cấu hình lại Vulkan.
- **Không** đổi bind address của Ollama (giữ `127.0.0.1:11434`).
- **Không** cài thêm package lên host ngoài các dependency Python trong venv tooling.
- **Không** sửa `.env`, không xoay secret, không đổi GPG backup (đã ổn định ở Step 1).
- **Không** sửa `docker-compose.yml` trong bất kỳ bước nào của Phase 0 (xem Phase 1+ concerns).

### 2.3. Phase 1+ concerns (ghi nhận, không giải quyết)
- **Ollama ↔ Docker networking**: Phase 0 chỉ cần host gọi `127.0.0.1:11434`. Phase 1 sẽ chốt phương án trong TDDoc Phase 1 (xem §3.10).
- **GPU/VRAM contention**: GTX 1650 4,2GB VRAM — không chạy Kronos và LLM 7B đồng thời; quyết định ở Phase 2/3.
- **Git identity thật**: identity tạm `haosanh-agent <haosanh@localhost>` chỉ dùng Phase 0; phải reset author trước khi push Phase 1.
- **File mốc `docs/status/phase0.md`** chứa commit hash: đưa vào backlog ở Step 6, không tạo bây giờ.
- **Chuyển secret ra khỏi cùng ổ đĩa** (password manager/offline): P0 blocker của Phase 10.
- **`docker-compose.yml` environment injection**: chỉ xem xét nếu topology thay đổi; không phải task Phase 0.

---

## 3. Proposed Design

### 3.1. Kiến trúc preflight

Preflight là một **CLI tool độc lập**, không phải runtime feature của ứng dụng. Nó không import code nghiệp vụ của QuantDinger; chỉ đọc filesystem, `.env`, gọi subprocess read-only và HTTP ra ngoài.

**Mô hình registry + profile:**

- Mỗi check là một đơn vị độc lập, có metadata tĩnh và một hàm thực thi.
- Một **registry** ánh xạ `profile → danh sách check ID`.
- `--profile` **mặc định `phase0`**; cho phép chỉ định rõ `--profile phaseN`. Profile không tồn tại → lỗi cấu hình (exit code 2), in danh sách profile hợp lệ.
- `phase1` … `phase9` là placeholder; mỗi profile = union(check phase0, check riêng của phase), sẽ được điền khi tới phase tương ứng.
- `--list-checks` in registry (ID, severity, timeout) để kiểm tra nhanh.
- `--offline` và `--tag network` là **thiết kế dành cho CI tương lai**, **chưa implement ở Phase 0** (xem §3.9).

**Bootstrap (chạy trước registry):**

1. **Wrapper `scripts/preflight`** (shell): xác định repo root, kiểm tra `scripts/.venv/bin/python` tồn tại. Thiếu → in hướng dẫn tạo venv và **exit 2**. Không dùng host Python 3.14.
2. **Interpreter guard** (Python, trước khi import dependency ngoài stdlib): kiểm tra `sys.version_info` là `3.12.x` và `sys.prefix` trỏ tới `scripts/.venv`. Sai → **exit 2**, không traceback.
3. **Nạp `.env`** qua parser có bọc lỗi + sanitizer (xem §3.5). Không nạp được → **exit 2**.
4. **Ollama warm-up** (không phải check): gọi `/api/generate` với prompt ngắn, budget riêng **30s**. Fail → **exit 2**.

**Check contract (mức thiết kế):**

| Trường | Ý nghĩa |
|---|---|
| `id` | Định danh duy nhất, snake_case (vd. `binance_testnet`) |
| `title` | Mô tả ngắn cho output |
| `severity` | `critical` \| `warning` |
| `timeout` | Timeout mặc định của check (giây); có thể override theo check |
| `requires` | Điều kiện tiên quyết: `env`, `docker`, `network`, `none` |
| `tags` | `local`, `network`, `secret`, `docker`, `git` (dùng cho lọc/nhóm) |
| `runner` | Hàm async thực thi, trả về `CheckResult` |

**`CheckResult` (mức thiết kế):** `status` ∈ {`PASS`, `FAIL`, `WARN`, `UNVERIFIED`, `SKIP`}; `detail` (chuỗi đã redact), `duration_ms`, `error_code` tùy chọn. Không chứa giá trị secret.

- `SKIP` **chỉ** dành cho check `warning`.
- Critical bị bỏ qua do rate limit hoặc hết budget → `UNVERIFIED` (exit 1).
- `WARN` không bao giờ đóng góp exit code, kể cả khi check có severity `critical`.

**Config source model (mounted `.env`):**

- Topology: `./.env` được bind-mount vào `/app/.env` cho backend/workers — **11 chỗ** trong `docker-compose.yml`; không service nào dùng `env_file:`.
- `backend_api_python/app/utils/config_loader.py` gọi `load_dotenv(env_path, override=False)`: process env của container thắng `.env`, nhưng container **không** nhận shell env của host trừ khi key được interpolate vào `environment:` hoặc khai báo tường minh.
- **8 key an toàn**: `LIVE_TRADING_ENABLED`, `JEV_ENABLED`, `LLM_PROVIDER`, `CUSTOM_API_URL`, `CUSTOM_MODEL`, `CUSTOM_API_KEY`, `SECRET_KEY`, `CREDENTIAL_ENCRYPTION_KEY` — phải chỉ đến từ mounted `.env`; không được xuất hiện trong `environment:` của bất kỳ service nào.
- Chỉ các key interpolated (ví dụ `POSTGRES_PASSWORD`, `DATABASE_URL`) mới có thể bị shell host override; đây là WARN, không safety-critical.

**Thứ tự thực thi:**

1. **Bootstrap** (mục trên): wrapper → interpreter guard → `.env` load → Ollama warm-up.
2. **Pha local (tuần tự, nhanh):** tooling → `.env`/secret/flags → config source → git → Docker plugin/compose/daemon → disk/disk pressure.
3. **Pha network (song song có giới hạn):** Ollama (service → model → smoke) và các endpoint ngoài (Binance, Jupiter, DexScreener).

Lý do tách pha: check cấu hình phải chạy trước để (a) phát hiện lỗi cấu hình sớm, (b) tránh gọi mạng khi secret/flags sai. Các check trong cùng pha chạy song song với **semaphore giới hạn 4** để không dồn tải lên mạng/CPU.

Output luôn được sắp xếp theo **thứ tự registry**, không theo thứ tự hoàn thành, để kết quả deterministic. Ngân sách mềm toàn bộ registry: **180s**; cạn budget khi còn critical chưa chạy → `UNVERIFIED` → exit 1.

### 3.2. Danh sách 22 check Phase 0

Tất cả timeout tính bằng giây. Ngưỡng pass ghi rõ ràng, không dựa vào "có vẻ ổn".

| # | Check ID | Mục tiêu | Cách đo | Pass condition | Timeout | Severity |
|---|---|---|---|---|---|---|
| 1 | `tooling_python` | Venv tooling đúng phiên bản | Đọc `sys.version_info` **bên trong** `scripts/.venv` | CPython `3.12.x`; fail → exit 2 (config) | 2s | critical |
| 2 | `host_python_info` | Thông tin Python trên host | `python3 --version` trên host | **Informational only**; không đóng góp exit code; detail ghi "tooling uses scripts/.venv" | 2s | warning |
| 3 | `env_file` | File cấu hình tồn tại và được bảo vệ | `stat` + resolve symlink + owner trên `.env` tại repo root | File thường (sau resolve), đọc được, `mode & 0o077 == 0`, owner là user hiện tại | 2s | critical |
| 4 | `env_required_keys` | Đủ key bắt buộc, không rỗng | Parse `.env` bằng `python-dotenv` (không mutate `os.environ`) | Có đủ 8 key: `SECRET_KEY`, `CREDENTIAL_ENCRYPTION_KEY`, `POSTGRES_PASSWORD`, `LLM_PROVIDER`, `CUSTOM_API_URL`, `CUSTOM_MODEL`, `LIVE_TRADING_ENABLED`, `JEV_ENABLED`; tất cả non-empty (trừ `CUSTOM_API_KEY` được phép rỗng) | 2s | critical |
| 5 | `durable_secrets` | Ba secret bền vững đủ mạnh, không mặc định | Đo độ dài + so danh sách đen | `SECRET_KEY >= 32`, `CREDENTIAL_ENCRYPTION_KEY >= 32`, `POSTGRES_PASSWORD >= 20`; không thuộc `{123456, password, postgres, changeme, admin}` | 2s | critical |
| 6 | `trading_safety_flags` | Không bật live/JEV | Parse boolean theo allowlist | `LIVE_TRADING_ENABLED` và `JEV_ENABLED` đều thuộc `{false, 0, no, off}` (case-insensitive); mọi giá trị khác, kể cả rỗng → FAIL critical | 2s | critical |
| 7 | `llm_config` | Trỏ đúng Ollama cục bộ | Parse `safe_url()` của `CUSTOM_API_URL` | `LLM_PROVIDER=custom`; host `127.0.0.1`; port `11434`; path `/v1`; `CUSTOM_MODEL=qwen2.5:1.5b`; `CUSTOM_API_KEY` rỗng hoặc không đặt | 2s | critical |
| 8 | `config_precedence` | Xác minh mounted `.env` + không override 8 key an toàn | `docker compose config --format json` in-memory; 3 bước | (a) `backend` + ≥1 worker mount `./.env:/app/.env` (có/không `:ro`); (b) 8 key an toàn **không** có trong `environment:` của bất kỳ service; (c) key interpolated lệch `.env` → WARN | 10s | critical (a,b); WARN (c) |
| 9 | `docker_compose_plugin` | Compose plugin có mặt | `docker compose version` | Exit 0; thiếu plugin → **exit 2** (config) | 5s | critical |
| 10 | `docker_compose_config` | Compose + `.env` hợp lệ | `docker compose config --quiet` tại repo root | Exit 0; compose invalid/interpolation error → **exit 2** (config); stderr redacted | 10s | critical |
| 11 | `docker_daemon` | Docker chạy được | `docker info --format '{{.ServerVersion}}'` | Exit 0 trong timeout, trả version không rỗng; fail → exit 1 | 5s | critical |
| 12 | `disk_free` | Đủ dung lượng cho Phase 0 | `shutil.disk_usage(repo_root)`; đo thêm Docker root nếu khác filesystem | Free `>= 20 GiB` (21,474,836,480 bytes) trên cả hai | 2s | critical |
| 13 | `docker_disk_pressure` | Thông tin áp lực dung lượng Docker | `docker system df` | WARN nếu tổng dùng > 80% hoặc không đọc được; **không** đóng góp exit code | 5s | warning |
| 14 | `git_identity` | Có identity local để commit | `git config --local --get user.name` / `user.email` | Cả hai non-empty | 2s | critical |
| 15 | `git_identity_temporary` | Cảnh báo identity tạm | So khớp `@localhost` hoặc `haosanh-agent` | WARN nếu là identity tạm; profile `phase0` chỉ hiện khi `--verbose`; profile `phase1+` hiện mặc định | 2s | warning |
| 16 | `env_gitignored` | Secret paths bị ignore và không bị track | `git check-ignore` cho **7 paths** + `git ls-files --error-unmatch` | Cả 7 paths ignored và không tracked: `.env`, `backend_api_python/.env`, `.keys/`, `secrets/`, `*.pem`, `*.key`, `*.gpg` | 5s | critical |
| 17 | `ollama_service` | Ollama phản hồi | `GET http://127.0.0.1:11434/api/version` | HTTP 200 + JSON có `version` | 2s | critical |
| 18 | `ollama_model` | Model Phase 0 có mặt | `GET /api/tags` | Danh sách chứa đúng tag `qwen2.5:1.5b` (không chấp nhận tag gần giống) | 5s | critical |
| 19 | `ollama_smoke` | Model sinh được token sau warm-up | `POST /api/generate` (`num_predict=1`, `stream=false`) | HTTP 200; chạy **sau** warm-up; **không retry** | 15s | critical |
| 20 | `binance_testnet` | Testnet reachable | `GET https://testnet.binance.vision/api/v3/ping` | HTTP 200, body `{}`; retry tối đa 2 lần | **8s/attempt** | critical |
| 21 | `jupiter_lite` | Jupiter Lite reachable | `GET https://lite-api.jup.ag/price/v3?ids=So11111111111111111111111111111111111111112` | HTTP 200, JSON chứa key mint SOL; 429 sau retry → FAIL critical | 5s/attempt | critical |
| 22 | `dexscreener` | DexScreener reachable | `GET https://api.dexscreener.com/latest/dex/search?q=SOL` | HTTP 200, JSON có mảng `pairs`; 429 sau retry → FAIL critical | 5s/attempt | critical |

**Ghi chú thiết kế cho từng nhóm:**

- Check 1–2 tách biệt để phân biệt "tooling sai" (exit 2) với "host Python chỉ là thông tin" (warning, exit 0).
- Check 3–8 **chỉ đọc** `.env` và compose config; không ghi, không backup, không in giá trị.
- `config_precedence` là check thay thế logic "so sánh 8 key từ compose config" ban đầu; lý do topology ở §3.1 và review file.
- Check 9–11 xác nhận Docker theo cách **read-only**; `docker compose config --quiet` không in nội dung ra stdout, nhưng stderr vẫn được redact trước khi hiển thị. Compose plugin/config fail → exit 2; daemon fail → exit 1.
- Check 12–13 đo dung lượng; `disk_free` critical, `docker_disk_pressure` chỉ warning.
- Check 14–16 bảo vệ git identity và secret hygiene; `env_gitignored` dùng đúng **7 paths** đã chốt.
- Check 17–19 chạy tuần tự trong cùng một "nhóm Ollama" để tránh 3 request đồng thời đánh thức model. Smoke chỉ chạy sau warm-up.
- Check 20–22 là **read-only GET**, không gửi API key, không đặt lệnh, không dùng tài khoản.

### 3.3. Timeout & retry strategy

**Timeout mặc định (đã chốt):**

| Loại | Timeout |
|---|---|
| HTTP check thường | **5s** / attempt |
| Binance testnet | **8s** / attempt (override riêng) |
| Ollama smoke | **15s**, **không retry**, chạy sau warm-up |
| Ollama warm-up (bootstrap) | **30s**, không phải check; fail → exit 2 |
| TCP/readiness | **2s** |
| Subprocess (`docker`, `git`) | 5s (`docker compose config` / `config_precedence`: 10s) |
| Toàn bộ registry | ngân sách mềm **180s**; critical chưa chạy khi hết budget → `UNVERIFIED` → exit 1 |

**Retry:**

- Network check (20–22): tối đa **2 retry** (3 attempt), backoff `0,5s → 1,5s` + jitter nhỏ.
- Chỉ retry khi: timeout, lỗi kết nối, HTTP `5xx`.
- **Không retry** khi: HTTP `4xx` (trừ `429`).
- `429 Too Many Requests`: retry có backoff, tôn trọng `Retry-After` nhưng không chờ quá 2s. Sau khi hết retry vẫn `429` → **FAIL critical** (không `SKIP`).
- Ollama smoke: **không retry**; cold start đã được xử lý bằng warm-up.
- `ollama_service`/`ollama_model` là critical và không phụ thuộc cold start.

Timeout được áp ở **hai lớp**: `httpx.Timeout` (connect/read) và `asyncio.wait_for` (tổng thời gian check), để một handler treo không kéo cả lượt chạy.

### 3.4. Severity & exit code

| Exit code | Ý nghĩa |
|---|---|
| **0** | Không có critical `FAIL`, không có `UNVERIFIED`. `WARN`/`SKIP` của warning được phép. |
| **1** | Có **ít nhất một critical `FAIL`** hoặc **critical `UNVERIFIED`** (bị bỏ qua do rate limit/hết budget). |
| **2** | **Lỗi cấu hình/bootstrap**, không phải lỗi môi trường: không tìm thấy `scripts/.venv`, venv sai Python, `.env` không tồn tại/không đọc được/parse hỏng, profile không hợp lệ, tham số CLI sai, registry rỗng, thiếu Compose plugin, compose invalid, Ollama warm-up fail. |

Quy tắc phân loại:

- `critical` + `FAIL` → exit 1, **trừ** các check được xếp vào nhóm config (`tooling_python`, `docker_compose_plugin`, `docker_compose_config`) → exit 2.
- `critical` + `UNVERIFIED` → exit 1; tổng kết ghi "UNVERIFIED — cần chạy lại".
- `warning` + `FAIL` → hiển thị `WARN` (màu vàng), exit 0.
- `warning` + `SKIP` → hiển thị `SKIP`, exit 0.
- `WARN` từ check critical (ví dụ `config_precedence` bước 3) → exit 0.
- `.env` **không nạp được** (không tồn tại/không đọc được/parse hỏng) → exit 2 **trước khi chạy registry**; `.env` đọc được nhưng mode không an toàn → `env_file` critical FAIL → exit 1.
- Lỗi bất ngờ trong lúc nạp cấu hình (không phải lỗi của một check) → exit 2.

`--strict` (tùy chọn tương lai, **không implement ở Phase 0**): biến warning thành fail. Không đưa vào scope. **Không có `--allow-live`** trong bất kỳ profile Phase 0.

### 3.5. Secret handling

Nguyên tắc: **secret chỉ tồn tại trong bộ nhớ, không bao giờ ra stdout/stderr/JSON/log/traceback.**

Cách đọc:

- Dùng `python-dotenv` ở chế độ **đọc thành mapping** (giá trị trả về), **không** mutate `os.environ` toàn cục. Điều này tránh secret bị kế thừa bởi subprocess (docker/git) và tránh rò rỉ qua môi trường tiến trình con.
- Không copy `.env` ra chỗ khác, không tạo file tạm chứa secret.
- Không truyền secret qua command-line argument (argv hiển thị trong `ps`).

Bọc parser và sanitizer:

- **Sanitizer được cài trước khi đọc `.env`**, không đợi parse xong.
- Sanitizer thay mọi giá trị secret đã biết bằng `***REDACTED***`. Nếu chưa biết giá trị (parser lỗi), fallback: thay mọi chuỗi alphanumeric ≥16 ký tự và mọi giá trị của 5 key bắt buộc (nếu nhận diện được dòng `KEY=`) bằng `***`.
- Bọc `load_dotenv()` và mọi parser trong `try/except`; **suppress toàn bộ warning/exception của dotenv**. Lỗi parser được chuyển thành lỗi nội bộ chỉ chứa: đường dẫn file + số dòng + loại lỗi. Không in raw line, không in `repr()` của exception gốc.
- Traceback chỉ in khi `--verbose`, và vẫn đi qua sanitizer.
- Compose-resolved config (`docker compose config --format json`) được đọc **in-memory**, chỉ trích xuất: tên service, sự tồn tại của mount, tên key bị override, và so sánh giá trị interpolated (`POSTGRES_PASSWORD`, `DATABASE_URL`, …) với `.env` để phát hiện shell override. Việc so sánh diễn ra trong bộ nhớ; **không serialize**, không ghi file, không log giá trị, không đưa giá trị vào `CheckResult.detail`.

Hiển thị:

- Cột `Detail` chỉ được chứa: **tên key**, **độ dài** (dạng "64 ký tự"), **trạng thái** ("đã đặt"/"rỗng"), **tên file**, **mode file**, **host/port** của URL (không kèm query/path chứa token).
- Không bao giờ in giá trị, kể cả một phần, kể cả hash.
- `safe_url()` chỉ giữ scheme + host + port + path; bỏ userinfo (`user:pass@`), query, fragment. Áp dụng cho mọi check có HTTP call hoặc so sánh URL.
- Redaction exact-match theo giá trị, chỉ áp dụng cho chuỗi **≥8 ký tự**; ưu tiên mask theo **key** thay vì thay thế mọi nơi.
- Bộ lọc redaction chạy trên **mọi** chuỗi output (human, JSON, exception, stderr subprocess).
- HTTP body của Ollama smoke không được log; chỉ log status, latency, số token.
- `--json` dùng schema cố định **không có trường value**; test sẽ assert không có giá trị secret nào xuất hiện trong output.
- **Test canary bắt buộc**: fixture chứa chuỗi đánh dấu duy nhất, gây lỗi parser, assert chuỗi không xuất hiện trong stdout, stderr, JSON. Test phải pass trước khi merge.

Quyền file:

- Check `env_file` chỉ **báo** mode; preflight **không** tự `chmod` (tránh thay đổi ngoài scope). Nếu mode sai → critical FAIL kèm hướng dẫn.

### 3.6. Output format

**Human-readable (mặc định):**

```
Phase 0 preflight — profile=phase0 — 2026-11-04T22:30:00+07:00

[PASS] tooling_python            CPython 3.12.15                        0.01s
[PASS] env_file                  .env mode 0600                         0.00s
[PASS] durable_secrets           SECRET_KEY=64, CREDENTIAL_ENCRYPTION_KEY=64, POSTGRES_PASSWORD=36   0.00s
[PASS] config_precedence          mounted .env verified; 8 safety keys not overridden   0.02s
[WARN] git_identity_temporary     temporary identity (reset before Phase 1)   0.01s
[FAIL] binance_testnet            timeout after 8s (3 attempts)          24.20s
[UNVERIFIED] jupiter_lite         429 rate limited after 3 attempts       0.80s

Summary: 16 PASS, 1 WARN, 1 FAIL (1 critical), 1 UNVERIFIED
Result: FAIL — exit 1
```

- Cột: `[STATUS]` | `Check ID` | `Detail` | `Duration`.
- Màu: xanh `PASS`, đỏ `FAIL` (critical), vàng `WARN`/`SKIP`/`UNVERIFIED`, khi terminal hỗ trợ.
- Tắt màu khi: không phải TTY, có `--no-color`, hoặc biến môi trường `NO_COLOR`.
- Độ rộng cột co giãn theo terminal; không cắt mất thông tin quan trọng (wrap thay vì truncate).

**JSON (`--json`):**

```json
{
  "schema_version": 1,
  "profile": "phase0",
  "generated_at": "2026-11-04T22:30:00+07:00",
  "environment": {
    "tooling_python": "3.12.15",
    "host_python": "3.14.4"
  },
  "checks": [
    {
      "id": "binance_testnet",
      "title": "Binance testnet reachable",
      "severity": "critical",
      "status": "FAIL",
      "detail": "timeout after 8s (3 attempts)",
      "duration_ms": 24200,
      "tags": ["network"]
    }
  ],
  "summary": {
    "pass": 16,
    "fail": 1,
    "warn": 1,
    "skip": 0,
    "unverified": 1,
    "critical_fail": 1,
    "critical_unverified": 1
  },
  "exit_code": 1
}
```

- Không có trường chứa giá trị secret.
- `--json` không in bất kỳ dòng log nào khác ra stdout (log đi stderr) để dùng được trong CI.
- Thứ tự `checks` cố định theo registry.
- `status` có thể là `PASS`, `FAIL`, `WARN`, `SKIP`, `UNVERIFIED`.

### 3.7. Python, venv và dependency

**Quyết định:**

- Tooling chạy trong venv riêng: **`scripts/.venv/`**.
- Interpreter: **CPython 3.12.15** do `uv` quản lý sẵn tại `~/.local/share/uv/python/cpython-3.12.15-linux-x86_64-gnu` (không tải thêm, không cần sudo).
- **Không** dùng host Python 3.14.4 (quá mới so với hệ sinh thái; tránh rủi ro tương thích của dependency và của QuantDinger).
- **Không** dùng venv của project cũ (đã không còn).
- `scripts/.venv/` đã được `.gitignore` bao phủ bởi pattern `.venv/` (dòng 69) — không cần sửa `.gitignore`.
- **Wrapper `scripts/preflight`** là entrypoint duy nhất; tự detect venv, nếu thiếu → exit 2 kèm hướng dẫn.

**Dependency (chỉ 4 gói, không thêm gì khác):**

| Gói | Vai trò | Ràng buộc đề xuất |
|---|---|---|
| `httpx` | HTTP client sync/async, timeout, MockTransport cho test | `>=0.27,<1.0` |
| `python-dotenv` | Đọc `.env` thành mapping | `>=1.0,<2.0` |
| `pytest` | Test runner | `>=8.0,<9.0` |
| `pytest-asyncio` | Test hàm async | `>=0.24,<1.0` |

Không dùng `requests`, không dùng `respx` (dùng `httpx.MockTransport` có sẵn), không dùng plugin pytest khác.

**Bootstrap (thực hiện ở Step 7, không phải bây giờ):**

```
uv venv --python 3.12 scripts/.venv
uv pip install --python scripts/.venv/bin/python httpx python-dotenv pytest pytest-asyncio
```

### 3.8. Test strategy

Testing pyramid cho preflight (số lượng điều chỉnh theo 22 check; tỷ lệ vẫn ~75/20/5):

| Tầng | Số lượng mục tiêu | Nội dung |
|---|---|---|
| **Unit** | ~50 test | Mỗi check function: happy path, fail path, edge case. Mock `httpx`, `subprocess`, `sys`, `shutil`, `git`. |
| **Integration** | ~14 test | `httpx.MockTransport` mô phỏng 200/429/500/timeout chậm; `.env` fixture trong tmp dir với giá trị giả; subprocess thật chỉ cho lệnh read-only an toàn (`git config`, `git check-ignore`). |
| **E2E** | 3 test | Chạy `scripts/preflight --profile phase0` thật trên máy này; chạy lại với `--json` kiểm tra schema; chạy với một endpoint bị chặn để kiểm tra exit code 1. |

Nguyên tắc test:

- **Không test chạm mạng thật** trong unit/integration; E2E là ngoại lệ có kiểm soát, đánh dấu `@pytest.mark.e2e`, mặc định skip, chạy thủ công trong Step 8.
- Timeout được test bằng handler chậm 0,2s với timeout 0,1s — không chờ 5s thật.
- **100% branch coverage** bắt buộc cho: sanitizer, exit-code classification, timeout/retry handling.
- **Secret leak test** bắt buộc: tạo `.env` fixture chứa giá trị đánh dấu duy nhất, chạy mọi nhánh (pass/fail/exception/parser error), assert chuỗi đánh dấu **không** xuất hiện trong stdout, stderr, JSON.
- Test `config_precedence`: thiếu mount → FAIL; có `environment:` override 8 key → FAIL; shell override interpolated → WARN (exit 0).
- Test `env_gitignored`: cả 7 paths ignored → PASS; một path không ignored → FAIL critical; `.env` bị track → FAIL.
- Test exit code 2: thiếu venv, sai Python, `.env` không đọc được, profile lạ, thiếu Compose plugin, compose invalid, warm-up Ollama fail.
- Test determinism: inject clock/`generated_at`, sắp xếp output theo registry.
- Coverage mục tiêu: `>= 90%` cho module check; không đặt coverage cho phần CLI formatting.

### 3.9. Profile & khả năng mở rộng

- `phase0`: implement đầy đủ **22 check** ở trên. Đây là profile **mặc định** khi không truyền `--profile`.
- `phase1` … `phase9`: placeholder trong registry; mỗi profile = union(check phase0, check riêng của phase), sẽ được điền khi tới phase tương ứng.
- Check dùng chung (docker, disk, secrets) được tái sử dụng giữa các profile; check đặc thù phase thêm sau.
- Không viết trước check cho Axiom/MT5/TradingView/Helius/OKX ở Phase 0 — chỉ chừa chỗ trong registry.
- `--offline` và `--tag network`: **design only**, chưa implement ở Phase 0; dùng cho CI tương lai.

### 3.10. Phase 1+ concerns (ghi nhận, không giải quyết ở Phase 0)

| Concern | Trạng thái Phase 0 | Ghi chú cho phase sau |
|---|---|---|
| Ollama ↔ Docker | Giữ `127.0.0.1:11434`; preflight chạy trên host | Phase 1 TDDoc chốt 1 trong 3: (A) bind `0.0.0.0` + firewall chỉ docker bridge (cần sudo); (B) `extra_hosts: host.docker.internal:host-gateway` + bind `127.0.0.1` (**khuyến nghị**); (C) Ollama trong compose network (tốn RAM, không hợp máy 6,6GB) |
| GPU | Chỉ ghi nhận GTX 1650 4,2GB VRAM | Phase 2: Kronos-mini CPU được; không chạy Kronos + LLM 7B đồng thời. Phase 3: quyết định dùng GPU cho LLM 7B nếu không chạy Kronos |
| Git identity | Identity tạm | Phase 1: reset author toàn bộ commit Phase 0 trước khi push |
| `docs/status/phase0.md` | Chưa tạo | Step 6 đưa vào backlog; ghi commit mốc `292473d` |
| Secret ngoài ổ đĩa | Chấp nhận rủi ro Phase 0–9 | Phase 10 P0 blocker: chuyển vào password manager/offline |
| Disk Phase 1 | Ngưỡng Phase 0 là 20 GiB | Profile `phase1` dùng **≥30 GiB**; điều chỉnh nếu pull thêm image |
| `docker-compose.yml` environment injection | Không sửa | Chỉ xem xét nếu topology thay đổi; không phải task Phase 0 |
| CI flags | Chưa implement | `--offline`, `--tag network` khi có CI |

---

## 4. Alternatives Considered

### 4.1. Phương án A — Shell script thuần (`bash` + `curl`/`jq`/`dig`)

- **Ưu:** không cần venv, chạy nhanh, ít dependency.
- **Nhược:** host **không có `curl`**; xử lý JSON/redaction/exit code phức tạp và dễ sai; rất khó unit test; output màu/JSON phải tự viết; phụ thuộc công cụ hệ thống khác nhau giữa máy.
- **Quyết định:** **không chọn.**

### 4.2. Phương án B — Dùng `pytest` làm runner chính

- **Ưu:** tận dụng fixture, assertion, plugin; test và chạy "cùng một chỗ".
- **Nhược:** pytest là framework test, không phải CLI vận hành; exit code/format màu/bảng/JSON cần plugin hoặc `conftest` phức tạp; khó kiểm soát thứ tự và ngân sách timeout; output mặc định không phù hợp báo cáo vận hành.
- **Quyết định:** **không chọn** làm runner. Pytest vẫn dùng để **test** preflight.

### 4.3. Phương án C — Python sync một file với `requests`

- **Ưu:** đơn giản, quen thuộc.
- **Nhược:** `requests` chỉ sync, khó chạy song song check mạng; timeout kém linh hoạt hơn `httpx`; không nhất quán với định hướng async HTTP của dự án (Tauric runner, bridge, execution adapter).
- **Quyết định:** **không chọn.**

### 4.4. Phương án D — Binary tĩnh (Go/Rust)

- **Ưu:** phân phối một file, không cần runtime.
- **Nhược:** thêm toolchain/build step, không cần thiết cho một tool nội bộ; khó tái sử dụng logic Python của dự án.
- **Quyết định:** **không chọn.**

### 4.5. Phương án E — Inject 8 key an toàn vào `environment:` của Compose

- **Ưu:** compose-resolved config sẽ chứa đủ 8 key; dễ so sánh trực tiếp.
- **Nhược:** **sửa `docker-compose.yml` ngoài scope Phase 0**; thêm `environment:` có thể vô tình override giá trị từ mounted `.env`, tạo regression nguy hiểm hơn lợi ích.
- **Quyết định:** **không chọn.** Phase 0 dùng Option A (`config_precedence` kiểm tra mounted `.env` + scan override). Nếu topology thay đổi, đó là task Phase 1+.

---

## 5. Risks & Mitigations

| # | Rủi ro | Khả năng | Tác động | Giảm thiểu |
|---|---|---|---|---|
| 1 | **Mạng chập chờn khi check Binance testnet** (đã từng đo 5,3s) | Trung bình | False FAIL, chặn Phase 0 | Timeout riêng **8s/attempt**; retry 2 lần + backoff; phân biệt timeout với HTTP 4xx; ghi rõ số attempt trong detail |
| 2 | **Ollama cold start 10,5s** | Cao ở lần đầu | False FAIL check smoke | Warm-up riêng 30s trước registry (fail → exit 2); smoke 15s, không retry, critical |
| 3 | **Jupiter/DexScreener rate limit (429)** | Trung bình | False FAIL | Retry có backoff + jitter; tôn trọng `Retry-After` tối đa 2s; sau retry vẫn 429 → **FAIL critical**, không `SKIP` |
| 4 | **Secret lộ qua exception traceback / warning dotenv** | Thấp nhưng nghiêm trọng | Rò rỉ bí mật | Sanitizer trước khi đọc; bọc parser; suppress warning; không mutate `os.environ`; traceback chỉ `--verbose` và đã redact; test canary bắt buộc |
| 5 | **`.env` cũ bị cache / đọc nhầm file** | Thấp | Kết quả sai | Đọc lại file mỗi lần chạy; đường dẫn tuyệt đối tới repo root; không dùng giá trị từ `os.environ`; kiểm tra `env_file` trước |
| 6 | **Docker daemon tắt / thiếu quyền** | Thấp | Check fail | `docker_daemon` critical (exit 1) với detail hành động được |
| 7 | **Đo disk sai filesystem** (repo vs Docker root) | Thấp | Đánh giá sai dung lượng | Đo `shutil.disk_usage(repo_root)` và Docker root riêng; báo cả hai; critical nếu một trong hai dưới ngưỡng |
| 8 | **Host Python 3.14 gây lỗi dependency** | Trung bình | Tool không chạy | Wrapper + venv pin 3.12.15; interpreter guard exit 2; `tooling_python` xác nhận lại |
| 9 | **`docker compose config` in secret ra stderr** | Thấp | Rò rỉ | Dùng `--quiet`; capture stdout/stderr; redact trước khi hiển thị; không log raw |
| 10 | **Chạy song song quá nhiều check mạng** | Thấp | Bị rate limit, timeout dây chuyền | Semaphore 4; nhóm Ollama chạy tuần tự; ngân sách toàn cục **180s** |
| 11 | **Shell override key interpolated (`POSTGRES_PASSWORD`, `DATABASE_URL`) gây lỗi auth/connection** | Trung bình | Container dùng giá trị khác `.env` | `config_precedence` bước 3 phát hiện và **WARN** (không đóng góp exit code); detail nêu tên key và hậu quả |
| 12 | **Ollama warm-up fail** (service down, model load lỗi) | Thấp | Preflight dừng sớm | Warm-up budget 30s; fail → **exit 2** với hướng dẫn `systemctl --user status ollama` |
| 13 | **Phase 1 hết đĩa khi pull/build image** | Trung bình | Build fail giữa chừng | Phase 0 ngưỡng 20 GiB; profile `phase1` dùng **≥30 GiB**; `docker_disk_pressure` cảnh báo sớm |
| 14 | **Topology thay đổi làm `config_precedence` bỏ sót** | Thấp | False PASS | Check xác minh mount thực tế + scan toàn bộ service; test fixture mô phỏng topology thay đổi |

---

## 6. Test Plan

### 6.1. Unit tests (~50)

- Mỗi check ID có tối thiểu: 1 happy path, 1 fail path, 1 edge case.
- Mock ở ranh giới: `httpx.AsyncClient`, `subprocess.run`, `sys.version_info`, `shutil.disk_usage`, `pathlib.Path.stat`.
- Các case bắt buộc:
  - `durable_secrets`: độ dài đúng/thiếu, giá trị mặc định, giá trị rỗng.
  - `trading_safety_flags`: `false`/`FALSE`/`0`/`no`/`off` pass; `true`/`1`/`yes`/`on`/rỗng/giá trị lạ fail.
  - `llm_config`: đúng host/port/path; sai port; URL có userinfo/query token (không được log token).
  - `env_file`: mode `0600`, `0644`, `0400`, symlink, file không tồn tại.
  - `disk_free`: đúng ngưỡng, dưới ngưỡng 1 byte.
  - `docker_disk_pressure`: dưới/trên 80%, lệnh lỗi.
  - `env_gitignored`: cả 7 paths ignored; một path không ignored; `.env` bị track.
  - `config_precedence`: thiếu mount; `environment:` override 8 key; shell override interpolated → WARN.
  - `ollama_model`: có/không có tag, tag gần giống (`qwen2.5:1.5b-instruct` không được tính).
  - `binance_testnet`/`jupiter_lite`/`dexscreener`: 200, 429, 500, timeout, JSON sai schema.
  - Exit code: critical fail → 1; critical unverified → 1; warning fail/warn → 0; lỗi cấu hình → 2.
  - `host_python_info`: không đóng góp exit code.
  - `git_identity_temporary`: suppress ở phase0, hiện khi `--verbose`.

### 6.2. Integration tests (~14)

- `httpx.MockTransport` cho toàn bộ check HTTP: 200, 429, 500, slow response (0,2s với timeout 0,1s).
- `.env` fixture trong `tmp_path` với giá trị giả (không dùng `.env` thật).
- `git config` và `git check-ignore` thật trong thư mục tạm (read-only, không ảnh hưởng repo).
- Compose JSON fixture mô phỏng: mounted `.env`, thiếu mount, `environment:` override, interpolated override.
- Kiểm tra output JSON đúng schema, có `severity`, `environment.tooling_python`, không có trường value.
- Kiểm tra thứ tự check deterministic.

### 6.3. E2E tests (3)

1. `scripts/preflight --profile phase0` trên môi trường thật → exit 0 (sau khi Step 7 hoàn tất).
2. `scripts/preflight --profile phase0 --json` → JSON hợp lệ, `schema_version=1`, không có secret.
3. Chạy với một endpoint bị chặn/mô phỏng lỗi → exit 1, báo cáo đúng check critical.

Tất cả E2E đánh dấu `@pytest.mark.e2e`, mặc định skip, chạy thủ công trong Step 8.

### 6.4. Test timeout, secret leak và branch coverage

- Timeout: dùng handler ngủ 0,2s, đặt timeout 0,1s → assert `FAIL`/`UNVERIFIED` đúng, thời gian chạy < 1s.
- Secret leak: fixture chứa chuỗi `LEAK_CANARY_...`; chạy pass/fail/exception/parser-error; assert chuỗi không xuất hiện trong stdout, stderr, JSON.
- **100% branch coverage** cho sanitizer, exit-code classification, timeout/retry handling.

### 6.5. Tiêu chí test pass

- 100% test pass.
- Không test nào chạm mạng thật ngoài E2E.
- Không có secret thật trong fixture hay log.
- Coverage module check `>= 90%`; 100% branch cho 3 khu vực bắt buộc ở §6.4.

---

## 7. Rollout Plan

### 7.1. Feature flag

**Không có.** Preflight là công cụ CLI vận hành, không phải runtime feature; không ảnh hưởng ứng dụng đang chạy. Không thêm biến môi trường, không thêm config vào `.env`.

### 7.2. Thứ tự triển khai

1. **Step 5** — Red-team review TDDoc + resolution (đã xong).
2. **Step 5.5** — Resolution + cập nhật TDDoc + commit (đã xong).
3. **Step 6** — Backlog + task breakdown (chờ duyệt).
4. **Step 7** — Tạo `scripts/.venv` (Python 3.12.15), cài 4 dependency, implement `scripts/preflight` + `scripts/preflight_check.py` + test.
5. **Step 8** — Chạy `--profile phase0` trên máy thật, lưu báo cáo, xác nhận exit 0 (chờ duyệt sang Phase 1).

### 7.3. Điều kiện coi Phase 0 hoàn tất

- TDDoc được duyệt và red-team resolution đầy đủ.
- Backlog có task breakdown rõ ràng.
- `scripts/preflight` và `scripts/preflight_check.py` tồn tại, có test, test pass.
- `scripts/preflight --profile phase0` trả **exit 0** trên máy này, **không có critical FAIL và không có UNVERIFIED**.
- Báo cáo preflight được lưu (human + JSON).
- Không có thay đổi nào ngoài phạm vi đã duyệt; repo sạch, commit mốc được ghi nhận.
- `LIVE_TRADING_ENABLED=false`, `JEV_ENABLED=false` vẫn giữ nguyên.

### 7.4. Rollback

- Xóa `scripts/.venv/`, `scripts/preflight`, `scripts/preflight_check.py` (cùng test) — không ảnh hưởng runtime.
- Không có migration dữ liệu, không có thay đổi Docker/Ollama.
- `.env` không bị sửa bởi preflight (chỉ đọc).
- `docker-compose.yml` không bị sửa trong Phase 0.

### 7.5. Bảo trì

- Khi thêm phase mới: bổ sung check vào registry, không sửa check Phase 0 trừ khi có lý do.
- Khi đổi endpoint provider: cập nhật check tương ứng + test.
- Khi Python tooling lên phiên bản mới: cập nhật pin trong TDDoc tương ứng và test lại.
- Khi topology Compose thay đổi: cập nhật `config_precedence` + test fixture.

---

## Phụ lục A — Bảng tổng hợp quyết định đã chốt

| Quyết định | Giá trị |
|---|---|
| Profile Phase 0 | `phase0` (mặc định) |
| Số check Phase 0 | **22** |
| Python tooling | CPython 3.12.15 (uv-managed), venv `scripts/.venv` |
| Entrypoint | `scripts/preflight` wrapper |
| Dependency | `httpx`, `python-dotenv`, `pytest`, `pytest-asyncio` (không thêm) |
| Timeout HTTP | 5s |
| Timeout Binance | 8s/attempt, 2 retry |
| Timeout Ollama warm-up | 30s (bootstrap, fail → exit 2) |
| Timeout Ollama smoke | 15s, không retry, critical |
| Timeout TCP | 2s |
| Global budget | 180s |
| Exit code | 0 pass / 1 critical FAIL hoặc UNVERIFIED / 2 config error |
| Critical bị skip | `UNVERIFIED` → exit 1 |
| Ollama bind Phase 0 | `127.0.0.1:11434` |
| Model Phase 0 | `qwen2.5:1.5b` |
| Disk threshold Phase 0 | ≥ 20 GiB |
| Disk threshold Phase 1 | ≥ 30 GiB (profile riêng) |
| Config source | Mounted `.env` + `config_precedence` 3 bước |
| Secret output | Không bao giờ in giá trị |
| `--allow-live` | Không có trong Phase 0 |
| Docker networking | Phase 1 concern |

## Phụ lục B — Lệnh tham chiếu (dùng ở Step 7/8)

```
# Tạo venv tooling (Step 7)
uv venv --python 3.12 scripts/.venv
uv pip install --python scripts/.venv/bin/python httpx python-dotenv pytest pytest-asyncio

# Chạy preflight (Step 8) — wrapper tự detect venv
scripts/preflight --profile phase0
scripts/preflight --profile phase0 --json > /tmp/preflight-phase0.json

# Chạy trực tiếp bằng interpreter trong venv (debug)
scripts/.venv/bin/python scripts/preflight_check.py --profile phase0

# Liệt kê check
scripts/preflight --list-checks
```

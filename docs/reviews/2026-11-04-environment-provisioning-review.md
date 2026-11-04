# Red-team Review — Environment Provisioning TDDoc

- **Ngày:** 2026-11-04
- **Đối tượng review:** `docs/design/2026-11-04-environment-provisioning.md`
- **Vai trò:** senior engineer khó tính, tìm lỗ hổng trước implementation
- **Phạm vi:** Phase 0 only
- **Trạng thái:** Đã chốt Resolution — **21/21 Chấp nhận** (#1 và #10 điều chỉnh kỹ thuật theo Option A)

---

## Tóm tắt

- **Số ý kiến:** 21
- **Mức độ:** Critical **3** / Major **9** / Minor **7** / Nit **2**
- **Khuyến nghị ban đầu:** **Approve with changes**
- **Kết quả Resolution:** **21/21 Chấp nhận** — không Từ chối, không Defer
- **Điều chỉnh kỹ thuật:** #1 và #10 chuyển từ "so sánh 8 key trong compose-resolved config" sang mô hình **mounted `.env` + `config_precedence` 3 bước** (xem Topology Correction)

**Nhận định tổng quát:** kiến trúc profile-based, tách secret handling và exit-code semantics là đúng hướng. Lỗ hổng lớn nhất không nằm ở code mà ở **nguồn sự thật của cấu hình**. Topology thực tế là **mounted `.env`**, không phải compose inject — điều này được xác minh và phản ánh trong Resolution #1.

---

## Resolution Summary

| # | Mức | Chủ đề | Quyết định |
|---|---|---|---|
| 1 | Critical | Precedence của config | **Chấp nhận có điều chỉnh (Option A)** — topology thực tế là mounted `.env`, không phải compose inject; thay bằng `config_precedence` 3 bước |
| 2 | Critical | Critical + SKIP vẫn exit 0 | **Chấp nhận** — critical + SKIP → exit 1; `SKIP` chỉ cho warning; JSON status `unverified` |
| 3 | Critical | Secret lọt qua exception | **Chấp nhận** — bọc parser, suppress warning dotenv, sanitizer mặc định, test canary bắt buộc |
| 4 | Major | Ollama cold start 10,5s | **Chấp nhận** — warm-up riêng (fail → exit 2); smoke 15s, critical, bỏ retry |
| 5 | Major | Binance 5,3s | **Chấp nhận** — Binance 8s/attempt, giữ 2 retry |
| 6 | Major | Global budget 120s | **Chấp nhận** — nâng 180s; cạn budget khi còn critical → exit 1 |
| 7 | Major | Exit-code mâu thuẫn | **Chấp nhận** — semantics 0/1/2 mới; `.env` không nạp được → 2, mode sai → 1 |
| 8 | Major | Bootstrap interpreter | **Chấp nhận** — wrapper `scripts/preflight` + guard; sai interpreter → exit 2 |
| 9 | Major | Compose vs daemon | **Chấp nhận** — tách `docker_compose_plugin` (2), `docker_compose_config` (2), `docker_daemon` (1) |
| 10 | Major | dotenv vs Compose | **Chấp nhận có điều chỉnh** — theo Option A; compose-resolved config chỉ dùng để kiểm tra override/mount |
| 11 | Major | URL credential | **Chấp nhận** — `safe_url()` bỏ userinfo/query/fragment; redaction exact-match ≥8 ký tự |
| 12 | Major | `--allow-live` | **Chấp nhận** — không có flag; parse boolean allowlist, giá trị khác → FAIL critical |
| 13 | Minor | `host_python_info` | **Chấp nhận** — đổi tên, informational, không đóng góp exit code |
| 14 | Minor | `[WARN]` thay `[FAIL] warning:` | **Chấp nhận** — dùng `[WARN]`, màu vàng, không đóng góp exit code |
| 15 | Minor | Disk Phase 1 | **Chấp nhận** — Phase 0 ≥20 GiB; profile phase1 ≥30 GiB |
| 16 | Minor | Warning fatigue | **Chấp nhận** — suppress `git_identity_temporary` ở phase0 (chỉ `--verbose`); bật ở phase1+ |
| 17 | Minor | 415 key trong `.env` | **Chấp nhận** — mặc định chỉ key bắt buộc; `--verbose` liệt kê key thiếu từ `.env.example` |
| 18 | Minor | Profile default | **Chấp nhận** — mặc định `phase0`; profile lạ → exit 2; profile = union(phase0, check riêng) |
| 19 | Minor | `env_file` mode + git track | **Chấp nhận** — pass khi `mode & 0o077 == 0`, owner hiện tại, resolve symlink; thêm `env_gitignored` 7 paths |
| 20 | Nit | JSON schema | **Chấp nhận** — `environment.tooling_python`; thêm `severity` vào mỗi check |
| 21 | Nit | Tỷ lệ test 45/12/3 | **Chấp nhận** — giữ tỷ lệ; E2E đánh dấu `@pytest.mark.e2e`; 100% branch coverage cho sanitizer/exit code/timeout |

**Chốt tổng:** 21/21 Chấp nhận. Không có ý kiến bị Từ chối hoặc Defer.

---

## Topology Correction

### Phát hiện

Resolution #1 ban đầu yêu cầu đọc **8 key an toàn** từ `docker compose config --format json` rồi so với `.env`. Kiểm chứng read-only trên repo này cho thấy điều đó **không khả thi nguyên văn**.

### Bằng chứng

- `docker compose config --services` → **18 service**.
- `backend` có **47** env key, nhưng **không có** `LIVE_TRADING_ENABLED`, `JEV_ENABLED`, `LLM_PROVIDER`, `CUSTOM_API_URL`, `CUSTOM_MODEL`, `CUSTOM_API_KEY`, `SECRET_KEY`, `CREDENTIAL_ENCRYPTION_KEY`.
- Trong 8 key an toàn, compose-resolved config chỉ chứa `POSTGRES_PASSWORD` (service `postgres`, và gián tiếp qua `DATABASE_URL`).
- Không service nào dùng `env_file:`.
- `./.env` được bind-mount vào `/app/.env` cho backend/workers — **11 chỗ** trong `docker-compose.yml`.
- `backend_api_python/app/utils/config_loader.py` gọi `load_dotenv(env_path, override=False)`: process env của container thắng `.env`, nhưng container **không** nhận shell env của host trừ khi key được interpolate vào `environment:` hoặc khai báo tường minh.
- Probe an toàn với biến giả `POSTGRES_PASSWORD=__PROBE_NOT_A_SECRET__`: compose config nhận đúng giá trị probe → xác nhận shell override **có** tác dụng với key interpolated (không in giá trị thật).

### Kết luận

- Rủi ro "shell export `LIVE_TRADING_ENABLED=true` làm container bật live" **không đúng** với topology hiện tại: key đó chỉ đến từ file `/app/.env` được mount.
- Rủi ro thật nằm ở: (a) service không mount `.env`; (b) ai đó thêm 8 key vào `environment:` của compose; (c) shell override các key interpolated như `POSTGRES_PASSWORD`/`DATABASE_URL`.

### Quyết định: Option A — so sánh có điều kiện + kiểm tra cơ chế mount

Thay Critical #1 bằng check `config_precedence` với 3 bước:

1. **Xác định mounted model:** parse `docker compose config --format json`; kiểm tra `backend` và ít nhất một worker có mount `./.env:/app/.env` (có hoặc không `:ro`). Thiếu → **FAIL critical**: "backend service does not mount .env; runtime config source unclear".
2. **Không override 8 key an toàn:** với mỗi service, kiểm tra `environment:` có chứa bất kỳ key nào trong 8 key an toàn. Có → **FAIL critical**: "service X overrides safety key Y via environment:; mounted .env can be bypassed".
3. **Shell override trên key interpolated:** so giá trị hiệu lực từ compose config với `.env` cho các key interpolated (`POSTGRES_PASSWORD`, `DATABASE_URL`, …). Lệch → **WARN**, không đóng góp exit code, detail nêu tên key và hậu quả auth/connection.

Bước 4 (giá trị 8 key hợp lệ trong `.env`) vẫn nằm ở `env_required_keys` và `trading_safety_flags` — **không trùng lặp**.

### Ảnh hưởng

- `docker-compose.yml` **không bị sửa** (đúng scope Phase 0).
- Tổng số check Phase 0: **22** (18 cũ + `config_precedence` + `env_gitignored` + `docker_disk_pressure` + `docker_compose_plugin`).
- Con số "20" trong chỉ đạo trước là miscount; đã chốt lại **22** với chủ dự án.

---

## Ý kiến chi tiết

### [Critical] #1 — Check an toàn chỉ đọc `.env`, bỏ qua precedence của môi trường

- **Vị trí trong TDDoc:** §3.1 Config source model, §3.2 check #8 `config_precedence`, §3.5 Secret handling.
- **Vấn đề:** Docker Compose có thứ tự ưu tiên: **biến môi trường của shell > file `.env`** cho các key interpolated. Preflight chỉ parse `.env` sẽ bỏ sót override. Tuy nhiên, topology thực tế là mounted `.env`: 6/8 key an toàn không đi qua compose `environment:`, nên shell host không tác động tới container.
- **Tác động nếu bỏ qua:** Có thể **false PASS** nếu ai đó thêm 8 key vào `environment:` hoặc nếu service không mount `.env`; đồng thời bỏ sót shell override trên key interpolated gây lỗi auth.
- **Đề xuất:** Thay bằng `config_precedence` 3 bước (mount verification → environment override scan → interpolated-key WARN). Không dùng `os.environ` để lấy secret; chỉ dùng để phát hiện xung đột.
- **Quyết định:** **Chấp nhận có điều chỉnh (Option A)** — topology thực tế là mounted `.env`, không phải compose inject. Chi tiết ở Topology Correction.

---

### [Critical] #2 — Critical check có thể `SKIP` và vẫn exit 0

- **Vị trí trong TDDoc:** §3.3, §3.4, §3.2 check #21/#22.
- **Vấn đề:** `jupiter_lite` và `dexscreener` là **critical**, nhưng gặp `429` sẽ thành `SKIP`; hết global budget cũng thành `SKIP`. Exit code khi đó vẫn `0` nếu các critical khác PASS.
- **Tác động nếu bỏ qua:** **False negative** — báo cáo xanh nhưng thực tế chưa kiểm chứng.
- **Đề xuất:** Critical + `SKIP` → **exit 1**; thêm trạng thái `UNVERIFIED`; `SKIP` chỉ dành cho warning; 429 sau retry → `FAIL` critical; budget cạn khi còn critical → `UNVERIFIED` (exit 1).
- **Quyết định:** **Chấp nhận.**

---

### [Critical] #3 — Secret có thể lọt qua exception trước khi redaction được thiết lập

- **Vị trí trong TDDoc:** §3.5, §3.4 (exit 2 khi không đọc được `.env`).
- **Vấn đề:** Redaction dựa trên **các giá trị đã parse được**. Nếu parser lỗi trước khi có danh sách giá trị, exception/warning có thể chứa chính dòng chứa secret.
- **Tác động nếu bỏ qua:** Secret lọt ra stderr/CI log — sự cố nghiêm trọng nhất mà TDDoc muốn ngăn.
- **Đề xuất:** Bọc parser trong try/except; suppress warning dotenv; sanitizer mặc định trước khi đọc file; traceback chỉ khi `--verbose` và vẫn qua sanitizer; test canary bắt buộc.
- **Quyết định:** **Chấp nhận.**

---

### [Major] #4 — Ollama smoke: timeout 10s thấp hơn cold start đo được 10,5s; retry không đáng tin

- **Vị trí trong TDDoc:** §3.1 Bootstrap, §3.2 check #19, §3.3.
- **Vấn đề:** Cold start thực đo **10,5s** > timeout **10s**. Retry có thể vẫn cold nếu model bị evict. Smoke là `warning` nên có thể che lỗi generation thật.
- **Tác động nếu bỏ qua:** False FAIL lần đầu hoặc false PASS khi generation hỏng.
- **Đề xuất:** Warm-up riêng (không phải check, budget 30s, fail → exit 2); smoke 15s một lần, bỏ retry, nâng thành **critical** sau warm-up.
- **Quyết định:** **Chấp nhận.**

---

### [Major] #5 — Binance testnet 5s timeout vs mẫu đo 5,3s

- **Vị trí trong TDDoc:** §3.2 check #20, §3.3.
- **Vấn đề:** Đã từng đo một mẫu 5,3s. Với timeout 5s, mẫu đó sẽ fail; worst case 3 attempt + backoff.
- **Tác động nếu bỏ qua:** False FAIL, chặn Phase 0 không có lý do.
- **Đề xuất:** Override timeout theo endpoint: Binance **8s/attempt**, giữ 2 retry + backoff.
- **Quyết định:** **Chấp nhận.**

---

### [Major] #6 — Global budget 120s quá sát và semantics khi cạn budget chưa an toàn

- **Vị trí trong TDDoc:** §3.3, §3.4.
- **Vấn đề:** Worst case có thể vượt 120s; khi vượt, critical bị `SKIP` → exit 0.
- **Tác động nếu bỏ qua:** Kết quả không ổn định; critical bị bỏ qua trong im lặng.
- **Đề xuất:** Nâng budget lên **180s**; budget bắt đầu sau bootstrap; cạn budget khi còn critical → `UNVERIFIED` → exit 1; log rõ check bị cắt.
- **Quyết định:** **Chấp nhận.**

---

### [Major] #7 — Mâu thuẫn exit code: "không đọc được `.env`" vừa là 2 vừa là 1

- **Vị trí trong TDDoc:** §3.4, §3.2 check #3.
- **Vấn đề:** Cùng một điều kiện được mô tả ở hai nơi với hai exit code khác nhau.
- **Tác động nếu bỏ qua:** Hành vi không nhất quán; CI/script dựa vào exit code sẽ xử lý sai.
- **Đề xuất:** Không nạp được cấu hình để chạy preflight (file không tồn tại/không đọc được/parse hỏng) → **exit 2**, trước khi chạy check. `.env` đọc được nhưng mode không an toàn → critical FAIL → **exit 1**.
- **Quyết định:** **Chấp nhận.**

---

### [Major] #8 — `tooling_python` không bảo vệ được lúc khởi động; sai interpreter gây exit 1 hoặc traceback

- **Vị trí trong TDDoc:** §3.1 Bootstrap, §3.7.
- **Vấn đề:** Nếu chạy `python3 scripts/preflight_check.py` (host 3.14), check #1 thấy 3.14 → critical FAIL → exit **1**, trong khi bản chất là **lỗi cấu hình (2)**. Nếu thiếu `httpx`, chương trình crash bằng `ImportError` trước khi in check nào.
- **Tác động nếu bỏ qua:** UX kém, exit code sai, output không đúng spec.
- **Đề xuất:** Wrapper `scripts/preflight` tự detect venv; bootstrap guard kiểm tra `sys.version_info == 3.12.x` và `sys.prefix` trỏ `scripts/.venv`; sai → exit 2, không traceback. E2E chạy host `python3` → exit 2.
- **Quyết định:** **Chấp nhận.**

---

### [Major] #9 — `docker_compose_config`: không cần daemon, nhưng đang bị xếp chung nhóm Docker; phân loại lỗi chưa rõ

- **Vị trí trong TDDoc:** §3.2 check #9/#10/#11, §3.4.
- **Vấn đề:** `docker compose config` **không cần Docker daemon**; có thể PASS khi daemon tắt. Thiếu Compose plugin hiện rơi vào check fail (1) thay vì lỗi cấu hình (2). Stderr có thể chứa giá trị interpolated.
- **Tác động nếu bỏ qua:** Chẩn đoán sai nguyên nhân; secret lọt qua stderr.
- **Đề xuất:** Tách 3 loại: `docker_compose_plugin` (thiếu plugin → exit 2), `docker_compose_config` (compose invalid/interpolation error → exit 2, stderr redacted), `docker_daemon` (daemon không chạy → exit 1).
- **Quyết định:** **Chấp nhận.**

---

### [Major] #10 — `python-dotenv` và Docker Compose parse `.env` khác nhau

- **Vị trí trong TDDoc:** §3.1 Config source model, §3.2 check #4/#5/#6/#7/#8, §3.5.
- **Vấn đề:** Compose hỗ trợ interpolation `${VAR}`/`$VAR`, quoting và escape khác `python-dotenv`. Một giá trị có thể đọc là `false` bằng dotenv nhưng resolve khác trong Compose.
- **Tác động nếu bỏ qua:** False PASS/FAIL; đặc biệt nguy hiểm với `LIVE_TRADING_ENABLED`.
- **Đề xuất:** Theo Option A: dùng compose-resolved config **in-memory** để kiểm tra mount/override/interpolated, không serialize; giá trị 8 key vẫn lấy từ mounted `.env` (đúng runtime model).
- **Quyết định:** **Chấp nhận có điều chỉnh** theo Option A.

---

### [Major] #11 — Chưa có sanitizer cho URL có credential; redaction theo giá trị ngắn có thể sai

- **Vị trí trong TDDoc:** §3.5.
- **Vấn đề:** `CUSTOM_API_URL` có thể chứa `https://user:pass@host/...` hoặc `?token=...`; nếu in nguyên URL khi so sánh/lỗi sẽ lộ credential. Nếu secret ngắn, thay thế toàn bộ chuỗi con có thể làm hỏng output.
- **Tác động nếu bỏ qua:** Lộ credential qua detail/JSON; output bị biến dạng.
- **Đề xuất:** `safe_url()` chỉ giữ scheme + host + port + path; bỏ userinfo/query/fragment. Redaction exact-match theo giá trị, chỉ áp dụng cho chuỗi ≥8 ký tự; ưu tiên mask theo key.
- **Quyết định:** **Chấp nhận.**

---

### [Major] #12 — `--allow-live`: tuyệt đối không cho phép ở Phase 0; nhưng phải parse truthy chặt

- **Vị trí trong TDDoc:** §3.2 check #6, §3.4.
- **Vấn đề:** Nếu thêm `--allow-live`, bất kỳ ai gõ thêm flag cũng bỏ qua bất biến an toàn. Check hiện chỉ so sánh `false`; cần chặn rõ mọi giá trị truthy và giá trị lạ.
- **Tác động nếu bỏ qua:** Vô tình bật live trong Phase 0; hoặc giá trị `0`/`no` bị coi là truthy.
- **Đề xuất:** **Không** có `--allow-live` trong Phase 0. Parse boolean allowlist: `false` = {`false`, `0`, `no`, `off`}; mọi giá trị khác (kể cả rỗng) → FAIL critical.
- **Quyết định:** **Chấp nhận.**

---

### [Minor] #13 — `system_python` nên đổi tên thành `host_python_info`

- **Vị trí trong TDDoc:** §3.2 check #2, §3.7.
- **Vấn đề:** Tên hiện tại gợi ý đây là điều kiện bắt buộc, trong khi tooling chạy bằng venv 3.12.15.
- **Tác động nếu bỏ qua:** Hiểu nhầm rằng host phải ≥3.10 mới chạy được preflight.
- **Đề xuất:** Đổi ID thành `host_python_info`, detail ghi "informational only; tooling uses scripts/.venv", không đóng góp exit code.
- **Quyết định:** **Chấp nhận.**

---

### [Minor] #14 — Hiển thị `[FAIL]` + `warning:` dễ gây nhầm; chuyển sang `[WARN]`

- **Vị trí trong TDDoc:** §3.6 Output.
- **Vấn đề:** `[FAIL] warning:` đánh lừa thị giác.
- **Tác động nếu bỏ qua:** Người đọc tưởng có fail critical.
- **Đề xuất:** Dùng `[WARN]`, màu vàng; exit code không đổi; JSON thêm `severity`.
- **Quyết định:** **Chấp nhận.**

---

### [Minor] #15 — Ngưỡng `disk_free ≥ 20 GiB` chỉ đúng cho Phase 0; Phase 1 cần ≥30 GiB

- **Vị trí trong TDDoc:** §3.2 check #12, §5 Risks.
- **Vấn đề:** Phase 1 pull/build QuantDinger có thể ngốn 15–20GB; 28,99 GiB hiện tại sẽ tụt về ~10 GiB.
- **Tác động nếu bỏ qua:** Phase 1 preflight fail hoặc hết đĩa giữa build.
- **Đề xuất:** Phase 0 = 20 GiB; profile phase1 = 30 GiB; profile-based, không hardcode.
- **Quyết định:** **Chấp nhận.**

---

### [Minor] #16 — `git_identity_temporary` gây warning fatigue trong Phase 0

- **Vị trí trong TDDoc:** §3.2 check #15.
- **Vấn đề:** Identity tạm là **hợp lệ** ở Phase 0, nhưng sẽ hiện warning mỗi lần chạy preflight.
- **Tác động nếu bỏ qua:** Mất tác dụng cảnh báo.
- **Đề xuất:** Suppress trong `--profile phase0` (chỉ hiện khi `--verbose`); bật thành warning/critical trong profile `phase1+`.
- **Quyết định:** **Chấp nhận.**

---

### [Minor] #17 — Chỉ kiểm 8 key trong `.env` 415 key; không báo key thiếu không bắt buộc

- **Vị trí trong TDDoc:** §3.2 check #4.
- **Vấn đề:** `.env` hiện có **415 key, 0 trùng**. Chỉ kiểm 8 key là đúng phạm vi, nhưng người dùng có thể không biết mình thiếu key tùy chọn quan trọng.
- **Tác động nếu bỏ qua:** Không lớn; chủ yếu là thiếu thông tin.
- **Đề xuất:** Mặc định chỉ kiểm key bắt buộc; `--verbose` liệt kê key có trong `.env.example` nhưng thiếu trong `.env` (chỉ tên key, không giá trị). Không đưa vào exit code.
- **Quyết định:** **Chấp nhận.**

---

### [Minor] #18 — Profile inheritance và default `--profile` chưa rõ

- **Vị trí trong TDDoc:** §3.1, §3.9.
- **Vấn đề:** "phase1…phase9 hiện kế thừa phase0 hoặc rỗng" là mơ hồ; không nói `--profile` bắt buộc hay mặc định.
- **Tác động nếu bỏ qua:** Implementer chọn khác nhau; hành vi không nhất quán.
- **Đề xuất:** `--profile` mặc định `phase0`; profile không tồn tại → exit 2; mỗi profile = union(phase0, check riêng của phase).
- **Quyết định:** **Chấp nhận.**

---

### [Minor] #19 — `env_file` yêu cầu chính xác `0600`; thiếu kiểm tra `.env` bị git track

- **Vị trí trong TDDoc:** §3.2 check #3 và #16, §3.5.
- **Vấn đề:** Mode `0400` cũng an toàn nhưng sẽ FAIL nếu kiểm chính xác `0600`; `.env` có thể là symlink; chưa có check xác nhận `.env` bị git ignore/không bị track.
- **Tác động nếu bỏ qua:** False FAIL với file read-only; hoặc bỏ sót nguy cơ commit `.env`.
- **Đề xuất:** Pass nếu `mode & 0o077 == 0` và owner là user hiện tại; resolve symlink và kiểm tra target; thêm check `env_gitignored` cho **7 paths**: `.env`, `backend_api_python/.env`, `.keys/`, `secrets/`, `*.pem`, `*.key`, `*.gpg`.
- **Quyết định:** **Chấp nhận** — dùng đúng 7 paths đã liệt kê.

---

### [Nit] #20 — JSON schema: field `tooling_python` ở top-level; thiếu `severity` trong check object

- **Vị trí trong TDDoc:** §3.6.
- **Vấn đề:** `tooling_python` là metadata môi trường, không nên nằm ngang hàng `checks`/`summary`; thiếu `severity` để CI phân biệt.
- **Tác động nếu bỏ qua:** Schema khó mở rộng, CI phải suy luận từ summary.
- **Đề xuất:** Đặt trong `environment.tooling_python`; thêm `severity` vào mỗi check; giữ `schema_version`.
- **Quyết định:** **Chấp nhận.**

---

### [Nit] #21 — Tỷ lệ test 45/12/3 (~75/20/5) lệch nhẹ pyramid; E2E chạm mạng thật

- **Vị trí trong TDDoc:** §6.
- **Vấn đề:** 3 E2E gọi mạng thật sẽ flaky trong CI.
- **Tác động nếu bỏ qua:** CI đỏ ngẫu nhiên; người dùng mất niềm tin vào test suite.
- **Đề xuất:** Chấp nhận 45/12/3 với lý do "nhiều boundary cần mock"; đánh dấu E2E `@pytest.mark.e2e`, mặc định skip, chạy thủ công trong Step 8. Bổ sung yêu cầu 100% branch coverage cho sanitizer, exit code, timeout handling.
- **Quyết định:** **Chấp nhận.**

---

## Phụ lục A — Checklist red-team cho 22 check

Ghi chú: "Idem" = chạy 2 lần liên tiếp có cùng status không. Các vấn đề chi tiết được tham chiếu bằng số issue.

| # | Check | Failure mode | Timeout / budget | Secret safety | Idem | Environment assumption | Testability |
|---|---|---|---|---|---|---|---|
| 1 | `tooling_python` | Sai interpreter → exit 1 thay vì 2; ImportError traceback (#8) | 2s | Không có secret | Có | Script được gọi bằng `scripts/.venv` — dễ vi phạm | Unit mock `sys`; E2E gọi host python |
| 2 | `host_python_info` | Warning gây hiểu nhầm là bắt buộc (#13) | 2s | Không | Có | `python3` có trên PATH; có thể không | Unit mock subprocess/path |
| 3 | `env_file` | Mode 0400 false fail; symlink; missing `.env` → exit 2 (#7, #19) | 2s | Chỉ stat, nhưng lỗi đọc có thể lộ path | Có (trừ khi file đang sửa) | POSIX perms | Unit tmp file + chmod |
| 4 | `env_required_keys` | dotenv vs compose khác nhau (#10); parser lỗi lộ secret (#3) | 2s | Rủi ro cao lúc parse (#3) | Có | Mounted `.env` là nguồn runtime | Unit tmp `.env` |
| 5 | `durable_secrets` | Chỉ đo độ dài; không phát hiện trùng key | 2s | Chỉ in độ dài — đúng | Có | `.env` là nguồn sự thật | Unit |
| 6 | `trading_safety_flags` | Truthy variants; giá trị lạ (#12) | 2s | Flag không phải secret | Có | `.env` mounted | Unit + allowlist test |
| 7 | `llm_config` | `localhost` false fail; URL credential lộ (#11) | 2s | URL có userinfo/query (#11) | Có | Ollama ở 127.0.0.1 | Unit |
| 8 | `config_precedence` | Thiếu mount; service override 8 key; shell override interpolated (#1) | 10s | Compose JSON đọc in-memory, không serialize | Có | Compose v2; mounted `.env` | Unit mock subprocess/JSON |
| 9 | `docker_compose_plugin` | Thiếu plugin → exit 2 (#9) | 5s | Không | Có | Compose v2 | Unit mock subprocess |
| 10 | `docker_compose_config` | Compose invalid/interpolation error → exit 2; stderr lộ secret (#9) | 10s | Stderr cần redact (#9) | Có | Compose v2 + cwd repo + `.env` | Unit temp compose |
| 11 | `docker_daemon` | Stale socket treo; remote context false pass; permission denied | 5s | Không | Gần như có | Daemon local, CLI có quyền | Unit mock subprocess |
| 12 | `disk_free` | Đo sai FS; Docker root không đọc được; ngưỡng Phase 1 (#15) | 2s | Không | **Không** (dung lượng đổi) | Repo và Docker root cùng FS | Unit mock `disk_usage` |
| 13 | `docker_disk_pressure` | `docker system df` chậm/lỗi | 5s | Không | **Không** | Daemon chạy | Unit mock subprocess |
| 14 | `git_identity` | Worktree/submodule; fallback global không phát hiện | 2s | Email là PII, không phải secret | Có | Git có, cwd trong repo | Unit temp repo |
| 15 | `git_identity_temporary` | False positive pattern khác; warning fatigue (#16) | 2s | Không | Có | Convention identity tạm | Unit |
| 16 | `env_gitignored` | Pattern ignore sai; `.env` bị track (#19) | 5s | Chỉ tên path, không đọc file | Có | `.gitignore` hiện tại | Unit temp repo |
| 17 | `ollama_service` | Bind IPv6-only; proxy chen ngang; 200 nhưng version lạ | 2s | Không | Có | 127.0.0.1:11434, không proxy | Unit MockTransport |
| 18 | `ollama_model` | Tag gần giống; model hỏng nhưng manifest có | 5s | Không | Có | Model đã pull | Unit MockTransport |
| 19 | `ollama_smoke` | Cold start; eviction; GPU OOM (#4) | 15s, no retry, sau warm-up | Không log prompt/response | Có sau warm-up | GPU/CPU, keep-alive | Unit slow handler |
| 20 | `binance_testnet` | 5,3s > 5s; geo-block; DNS; 451/403 (#5) | 8s/attempt, 2 retry | Không (public) | **Không** (mạng) | Internet, không proxy | Unit MockTransport |
| 21 | `jupiter_lite` | 429 sau retry → FAIL critical (#2); schema đổi | 5s/attempt, 2 retry | Không | **Không** | Internet, `lite-api.jup.ag` | Unit MockTransport |
| 22 | `dexscreener` | 429 sau retry → FAIL critical (#2); payload lớn | 5s/attempt, 2 retry | Không | **Không** | Internet | Unit MockTransport |

---

## Câu hỏi mở cho chủ dự án

1. **Binance testnet ở Phase 0:** chỉ cần kiểm tra reachability (`/api/v3/ping`), hay cần kiểm tra API key testnet hợp lệ bằng một request có chữ ký?
2. **Có thêm check `env_gitignored` không?** Đây là defense-in-depth cho secret.
3. **`--profile` bắt buộc hay mặc định `phase0`?**
4. **Có cần preflight chạy trong CI không?**
5. **Phase 1 ngưỡng disk ≥30 GiB** — xác nhận con số, hay tính theo kích thước image thực tế?
6. **`--allow-live`:** xác nhận tuyệt đối không có ở Phase 0?
7. **Có cần kiểm tra dung lượng Docker (`docker system df`) trong Phase 0 không?**

---

## Answers from Owner

1. **Binance testnet:** **Reachability only** ở Phase 0 (`GET /api/v3/ping`). Không kiểm API key chữ ký; để Phase 1 khi test execution thực sự. Phase 0 chưa có credential testnet, reachability đủ chứng minh network path.
2. **`env_gitignored`:** **CÓ, thêm.** Chạy `git check-ignore` cho **7 paths**: `.env`, `backend_api_python/.env`, `.keys/`, `secrets/`, `*.pem`, `*.key`, `*.gpg`. Bất kỳ path nào không bị ignore → FAIL critical. Tên check: `env_gitignored`.
3. **`--profile`:** **Mặc định `phase0`**, cho phép explicit `--profile phaseN`. Profile không tồn tại → exit 2. Dev local không cần nhớ flag; CI/script có thể chỉ định rõ.
4. **CI:** Phase 0 **không cần CI**. Thiết kế phải hỗ trợ `--offline` và `--tag network` (chỉ chạy check không cần network) để dùng sau này; **chưa implement ở Phase 0**, chỉ design.
5. **Phase 1 disk:** **Xác nhận ≥30 GiB.** QuantDinger images ~15–20GB + Ollama models (1.5B đã có, có thể thêm 7B ~4.7GB) + Kronos cache ~2GB + Docker overhead ~5GB. Điều chỉnh trong profile `phase1` nếu pull thêm image.
6. **`--allow-live`:** **XÁC NHẬN KHÔNG** trong bất kỳ profile Phase 0. Ai cần live phải sửa `.env` thủ công và chấp nhận preflight fail — đó là fail-fast đúng.
7. **`docker_disk_pressure`:** **CÓ, thêm như warning.** Dùng `docker system df`, hiển thị dung lượng images/cache/volumes; không đóng góp exit code.

**Ghi chú số check:** sau khi áp dụng Option A và tách `docker_compose_plugin`, tổng số check Phase 0 là **22**, không phải 20. Đã xác nhận với chủ dự án.

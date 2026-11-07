# Git sync workflow

- `origin` = `git@github.com:camd21808-lab/QuantDinger.git` (fork)
- `upstream` = `https://github.com/OpenByteInc/QuantDinger.git`

## Sync với upstream (OpenByteInc/QuantDinger)

Khi cần lấy cập nhật từ upstream:

```sh
git fetch upstream
git rebase upstream/main    # rebase, không merge
# resolve conflict nếu có, không force-push
git push origin main
```

## Push lên fork

```sh
git push origin main
git push origin setup/environment-provisioning
```

Không dùng `--force` / `--force-with-lease` trừ khi có lý do được owner duyệt rõ ràng.

## Lưu ý cho Phase 1

Không tự động rebase upstream trong Phase 1 trừ khi thật cần thiết (có thể gây conflict
với code đã sửa). Chỉ rebase khi có lý do rõ ràng: security fix hoặc bug fix quan trọng
từ upstream.

`main` đang track `origin/main` (do `git push -u`). Muốn so sánh với upstream:

```sh
git log --oneline upstream/main..HEAD
git log --oneline HEAD..upstream/main
```

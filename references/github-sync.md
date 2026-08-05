# 框架仓库 GitHub 同步（zhang20080215/a-share-short-term-analysis）

本技能目录 = 用户 GitHub 公开仓库的本地镜像。同步是重复性任务，流程如下。

## 仓库信息

- 远程：`https://github.com/zhang20080215/a-share-short-term-analysis.git`
- 用户名：`zhang20080215`（git 身份：user.name=zhang20080215, user.email=zhang20080215@users.noreply.github.com）
- 可见性：**public**（任何人可读 → 敏感信息/凭据严禁入库）
- 本地目录：`~/.hermes/skills/software-development/a-share-short-term-analysis/`（已是 git 仓库，分支 main）

## 推送流程

```bash
cd ~/.hermes/skills/software-development/a-share-short-term-analysis
git add -A
git commit -m "选股框架更新：..."
git push https://zhang20080215:<TOKEN>@github.com/zhang20080215/a-share-short-term-analysis.git main
```

## ⚠️ Fine-grained PAT 陷阱（2026-08-05踩坑）

- 用户提供的是 **fine-grained PAT**（`github_pat_` 开头），默认**对该仓库无写权限**。
- 症状：`git push` → `remote: Permission to ... denied` / HTTP 403。
- 验证 token 是否有效（读权限）：`curl -H "Authorization: Bearer <TOKEN>" https://api.github.com/user`（返回 login 即有效）——但有效≠能写。
- **修复**：用户需在 GitHub → Settings → Developer settings → Personal access tokens → Fine-grained tokens → 编辑该 token：
  - Repository access 勾选 `a-share-short-term-analysis`
  - Permissions → Repository permissions → Contents 设为 **Read and write**
- 完成后重试 push。已确认 token 的 login=zhang20080215、仓库 private=False、default_branch=main。

## 网络注意

- `github.com` 主站间歇性超时（git 协议连 443 失败），但 `api.github.com` 通常可达。
- push 前可先 `curl -sI https://github.com` 探测；超时则等待重试，不要反复空跑。
- push 用 `timeout 120` 包裹，避免无限挂起；大仓库可后台 push + notify_on_complete。

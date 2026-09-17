# FOLIO 折页（Postgres 版）

多语种原版书推荐网站。杂志式荐读，不提供购买。

本仓库是 `folio-zheye` 的独立副本：**用户、评论、收藏写入免费 Postgres（Neon / Supabase）**，部署更新不会清空账号。本机未设置 `DATABASE_URL` 时仍用 SQLite，方便开发测试。

## 本地启动

```bash
cd "/Users/zhangfanfan/Desktop/inspiration/folio-zheye-pg"
python3 -m pip install -r requirements.txt
python3 -m folio.seed
python3 run.py
```

浏览器打开 `http://127.0.0.1:8000`。

## 测试

```bash
python3 -m pytest tests -q
```

## 接免费 Postgres（推荐 Neon）

1. 打开 [Neon](https://neon.tech) 注册，新建一个项目，复制连接串（形如 `postgresql://user:pass@host/db?sslmode=require`）。
2. 本地试跑：

```bash
export DATABASE_URL='postgresql://...'
python3 -m folio.seed
python3 run.py
```

3. 部署到 Render 时，在服务环境变量里填同一条 `DATABASE_URL`（`render.yaml` 已声明该变量，需在控制台粘贴真实连接串）。**不要把密码写进 Git。**

也可用 [Supabase](https://supabase.com) 的 Postgres 连接串，环境变量名同样是 `DATABASE_URL`。

## 部署到 Render（本仓库）

仓库建议名：`folio-zheye-pg`。

1. 用 Blueprint 连接本仓库，服务名 `folio-zheye-pg`。
2. `FOLIO_SECRET_KEY` / `FOLIO_ADMIN_KEY` 自动生成后请长期固定，不要每次改。
3. 在 Environment 填入 Neon 的 `DATABASE_URL`。
4. **不需要付费磁盘**：账号在 Postgres；容器里的 `/app/data` 只存临时上传文件（头像等）。若要永久保存头像，可再自行加磁盘或对象存储。

管理员：用 `1797098277@qq.com` 注册后自动成为管理员。

## 与原版 SQLite 仓库的关系

- 原仓库 `folio-zheye` 继续走 SQLite +（可选）Render 磁盘，互不影响。
- 本仓库改库后端与部署说明，书目与页面逻辑同源。

## 读者账号

- 登录 `/login`，注册 `/register`，个人中心 `/account`
- 访客可浏览、评论；登录后可收藏、投稿
- 密码 Argon2 / PBKDF2；会话 Cookie `folio_sid`

## 封面优化（WebP + AVIF + 可选 CDN）

列表：`*-240/320` 的 AVIF→WebP；详情：`*-600` AVIF→WebP。

```bash
python3 scripts/trim_cover_borders.py --also-provided
python3 scripts/optimize_covers.py          # 缺什么补什么（含 AVIF）
python3 -m folio.seed
```

### 放到 Cloudflare R2 / S3（推荐上线后做）

1. 建公开读的 bucket，记下 S3 API endpoint 与公开域名。  
2. 本机上传变体文件：

```bash
export FOLIO_S3_ENDPOINT='https://<accountid>.r2.cloudflarestorage.com'
export FOLIO_S3_ACCESS_KEY='...'
export FOLIO_S3_SECRET_KEY='...'
export FOLIO_S3_BUCKET='folio-covers'
export FOLIO_S3_PUBLIC_BASE='https://pub-xxxxx.r2.dev'   # 或自定义域名
python3 -m pip install boto3
python3 scripts/upload_covers_s3.py
```

3. 在 Render 环境变量设置同一公开源：

```bash
FOLIO_COVER_BASE_URL=https://pub-xxxxx.r2.dev
```

库里仍存相对路径（如 `/covers/foo.jpg`）；页面渲染时自动拼 CDN。未设置时继续由本站 `/covers/` 提供。


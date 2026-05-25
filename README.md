# 飞书 AI 日报自动推送

每天早上 8:00 自动抓取 [AI HOT](https://aihot.virxact.com) 资讯，精选 15 条生成日报长图并推送到飞书群。

## 特性

- 从 AI HOT API 自动抓取 AI 行业最新动态
- 按行业动态 / 产品发布 / 论文研究 / 技巧观点 四大分类精选
- 生成 1086px 宽精美信息长图（含纹理背景 + 分类标注 + 序号徽章）
- 配套 Markdown 深度分析文案
- 通过飞书开放平台 API 自动推送到指定群聊
- GitHub Actions 每日自动执行，无需自备服务器

## 快速开始

### 1. Fork 本仓库

### 2. 配置 GitHub Secrets

在仓库 Settings → Secrets and variables → Actions 中添加：

| Secret 名 | 值 |
|---|---|
| `FEISHU_APP_ID` | 飞书开放平台应用的 App ID |
| `FEISHU_APP_SECRET` | 飞书开放平台应用的 App Secret |
| `FEISHU_CHAT_ID` | 目标飞书群的 Chat ID |

### 3. 飞书应用权限

确保飞书应用已开通以下权限（只需开通无需审批）：

- `im:resource:upload` — 上传图片
- `im:message:send_as_bot` — 机器人发送消息

### 4. 运行

#### GitHub Actions（推荐）

每天 UTC 0:00（北京时间 8:00）自动运行。也可以手动触发：

仓库 → Actions → AI每日日报推送 → Run workflow

#### 本地运行

```bash
pip install -r requirements.txt

# 仅生成（不推送）
python daily_push.py --output-dir output --skip-push

# 完整流程（设置环境变量后）
export FEISHU_APP_ID=cli_xxx
export FEISHU_APP_SECRET=xxx
export FEISHU_CHAT_ID=oc_xxx
python daily_push.py --output-dir output
```

## 目录结构

```
feishu-ai-daily/
├── .github/workflows/
│   └── daily_push.yml    # GitHub Actions 定时任务
├── daily_push.py          # 全流程主脚本
├── requirements.txt       # Python 依赖
└── README.md
```

每次运行产出：
- `output/ai_daily_YYYYMMDD.png` — 日报长图
- `output/AI日报_YYYYMMDD.md` — 分析文案